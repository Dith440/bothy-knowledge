"""Pack files: knowledge packs as single .zip files, to back up, pass on, or share with the community.

A pack file is a zip with one folder inside, named after the pack id, holding the pack exactly as it is on a
device (see bothy_packs). Two kinds of export:

    backup      everything, as it is; for your own decks
    shareable   only what may be shared: the texts need an open licence, and pictures without one are left out
                (with whatever shows them); the pack is marked shareable

Importing checks a file before anything is written: zip safety (paths, links, sizes), the pack format, that every
picture is a real picture and SVGs carry no scripts, and that the pack compiles. Then it is added as a new pack,
replaces the pack with the same id (the old one is kept aside), or is added as a copy under a new id.
"""
import datetime
import io
import json
import os
import re
import shutil
import tempfile
import zipfile

import bothy_packs
from bothy_packs import PackError, SLUG, CATEGORY_IMAGES

OPEN_LICENCES = ("CC0", "CC0 1.0", "CC BY 4.0", "CC BY-SA 4.0", "Public domain")
PICTURE_EXT = (".webp", ".png", ".jpg", ".jpeg", ".svg", ".gif")
DOCUMENT_EXT = (".pdf",)
LICENSED_EXT = PICTURE_EXT + DOCUMENT_EXT  # files that carry a licence of their own
ALLOWED_EXT = (".json", ".md", ".txt") + LICENSED_EXT
MAX_FILES = 20000
MAX_TOTAL = 2 * 1024 ** 3
MAX_FILE = 50 * 1024 ** 2
MAX_RATIO = 200
SUFFIX = ".bothy-pack.zip"


def is_open(licence):
    return str(licence or "").strip().lower() in {x.lower() for x in OPEN_LICENCES}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# What a pack holds ------------------------------------------------------------------------------------------

def pictures(pack_dir):
    """Every picture in a pack with its licence: [{"file": relative path, "licence", "author", "source"}]."""
    return [f for f in licensed_files(pack_dir) if f["file"].lower().endswith(PICTURE_EXT)]


def licensed_files(pack_dir):
    """Every picture and document in a pack with its licence: [{"file": relative path, "licence", "author", "source"}]."""
    out = []
    for root, dirs, files in os.walk(pack_dir):
        dirs.sort()
        for name in sorted(files):
            if name.lower().endswith(LICENSED_EXT):
                path = os.path.join(root, name)
                info = _read(os.path.splitext(path)[0] + ".json", {})
                out.append({"file": os.path.relpath(path, pack_dir).replace(os.sep, "/"),
                            "licence": info.get("licence", ""), "author": info.get("author", ""),
                            "source": info.get("source", "")})
    return out


def summary(pack_dir):
    """What a pack is and holds, for the editor and for the import preview."""
    meta = _read(os.path.join(pack_dir, "pack.json"))
    pics = pictures(pack_dir)
    out = {"id": meta.get("id"), "kind": meta.get("kind"), "title": meta.get("title"), "version": meta.get("version"),
           "licence": meta.get("licence", ""), "private": meta.get("private", True), "authors": meta.get("authors", []),
           "pictures": len(pics), "openPictures": sum(1 for p in pics if is_open(p["licence"]))}
    if meta.get("kind") == "medical":
        out["protocols"] = len(meta.get("protocolOrder", []))
        out["medications"] = len(_read(os.path.join(pack_dir, "medications.json"), {}).get("medications", []))
        out["reviewed"] = sum(1 for pid in meta.get("protocolOrder", [])
                              if _read(os.path.join(pack_dir, "protocols", pid, "protocol.json"), {})
                              .get("reviewState", {}).get("state") == "reviewed")
    else:
        guides = 0
        reviewed = 0
        for cat in meta.get("categoryOrder", []):
            for gid in _read(os.path.join(pack_dir, cat, "category.json"), {}).get("guideOrder", []):
                guides += 1
                g = _read(os.path.join(pack_dir, cat, gid, "guide.json"), {})
                reviewed += g.get("review", {}).get("state") == "reviewed"
        out.update({"categories": len(meta.get("categoryOrder", [])), "guides": guides, "reviewed": reviewed})
    return out


def share_problems(pack_dir):
    """Why a pack can't go to the community collection as it is (empty when it can)."""
    meta = _read(os.path.join(pack_dir, "pack.json"))
    problems = []
    if not is_open(meta.get("licence")):
        problems.append(f"the texts need an open licence (CC BY-SA 4.0, CC BY 4.0 or CC0), not {meta.get('licence') or 'none'}")
    if meta.get("private", True):
        problems.append("the pack is marked private")
    for pic in licensed_files(pack_dir):
        if not is_open(pic["licence"]):
            problems.append(f"{pic['file']}: licence {pic['licence'] or 'missing'}")
        elif not pic["author"] or not pic["source"]:
            problems.append(f"{pic['file']}: says who made it and where it comes from? (author and source are needed)")
    return problems


# Export -----------------------------------------------------------------------------------------------------

def _referenced_sources(guides, categories_info):
    ids, verification = set(), set()
    for g in guides:
        ids |= {r.get("sourceId") for r in g.get("sourceRefs", [])}
        verification |= {r.get("sourceId") for r in g.get("externalRefs", [])}
    for info in categories_info:
        ids |= set(info.get("sourceIds", []))
        verification |= set(info.get("verificationSourceIds", []))
    return ids, verification


def _copy_selection(src, dest, categories=None, guides=None):
    """Copy a knowledge pack, or only some categories (whole) or guides ("cat/guide"), into dest."""
    meta = _read(os.path.join(src, "pack.json"))
    if categories is None and guides is None:
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.tmp", ".*"))
        return
    wanted = {}
    for cat in categories or []:
        if cat not in meta.get("categoryOrder", []):
            raise PackError(f"the pack has no category {cat}")
        wanted[cat] = None  # whole category
    for item in guides or []:
        cat, _, gid = item.partition("/")
        if cat not in meta.get("categoryOrder", []) or gid not in _read(os.path.join(src, cat, "category.json")).get("guideOrder", []):
            raise PackError(f"the pack has no guide {item}")
        if wanted.get(cat, []) is not None:
            wanted.setdefault(cat, []).append(gid)
    os.makedirs(dest)
    order = [c for c in meta["categoryOrder"] if c in wanted]
    infos, structures = [], []
    for cat in order:
        info = _read(os.path.join(src, cat, "category.json"))
        if wanted[cat] is None:
            shutil.copytree(os.path.join(src, cat), os.path.join(dest, cat), ignore=shutil.ignore_patterns("*.tmp", ".*"))
            gids = info["guideOrder"]
        else:
            # Single guides travel with a plain category: id, intro and their sections, nothing the category shows itself.
            gids = [g for g in info["guideOrder"] if g in wanted[cat]]
            sections = {}
            for gid in gids:
                sid = _read(os.path.join(src, cat, gid, "guide.json")).get("sectionId")
                sec = dict(info.get("sections", {}).get(sid, {"description": {"en": "", "de": ""}}))
                if "guideIds" in sec:
                    sec["guideIds"] = [x for x in sec["guideIds"] if x in gids]
                sections[sid] = sec
            shelf = {k: info[k] for k in ("title", "description", "icon", "group", "custom") if k in info}
            info = {"id": cat, "intro": info.get("intro", {"en": "", "de": ""}), "sections": sections, **shelf,
                    "fieldOrder": ["id", "intro", "sections", "guides", "lexicon", "references"] + list(shelf),
                    "guideOrder": gids}
            _write(os.path.join(dest, cat, "category.json"), info)
            _write(os.path.join(dest, cat, "lexicon.json"), [])
            _write(os.path.join(dest, cat, "references.json"), [])
            for gid in gids:
                shutil.copytree(os.path.join(src, cat, gid), os.path.join(dest, cat, gid))
        infos.append(info)
        for gid in gids:
            structures.append(_read(os.path.join(src, cat, gid, "guide.json")))
    ids, verification = _referenced_sources(structures, infos)
    sources = _read(os.path.join(src, "sources.json"), {})
    out = {}
    if "sources" in sources:
        out["sources"] = [s for s in sources["sources"] if s.get("id") in ids]
    if "verificationSources" in sources:
        out["verificationSources"] = [s for s in sources["verificationSources"] if s.get("id") in verification]
    _write(os.path.join(dest, "sources.json"), out)
    meta["categoryOrder"] = order
    content = meta.get("content", {})
    if "publishedCategoryIds" in content:
        content["publishedCategoryIds"] = [c for c in content["publishedCategoryIds"] if c in order] or order
    _write(os.path.join(dest, "pack.json"), meta)


def _shows(item, urls):
    """Whether a dict itself shows one of urls (in its own fields, not in lists inside it, such as a page's blocks)."""
    for value in item.values():
        if isinstance(value, str) and value in urls:
            return True
        if isinstance(value, dict) and _shows(value, urls):
            return True
    return False


def _drop_urls(value, urls):
    """Remove what shows one of urls: list entries (dicts) that show one are left out, other values emptied."""
    if isinstance(value, str):
        return "" if value in urls else value
    if isinstance(value, list):
        kept = []
        for item in value:
            if isinstance(item, dict) and _shows(item, urls):
                continue
            kept.append(_drop_urls(item, urls))
        return kept
    if isinstance(value, dict):
        return {k: _drop_urls(v, urls) for k, v in value.items()}
    return value


def _make_shareable(pack_dir, report):
    """Leave out pictures without an open licence, and what shows them; report what was left out."""
    meta = _read(os.path.join(pack_dir, "pack.json"))
    removed = report.setdefault("leftOut", [])
    private = {p["file"]: p for p in licensed_files(pack_dir) if not is_open(p["licence"])}
    # Documents that may not be shared: the source stays cited, without its file.
    documents = {url for url, name in bothy_packs.pack_files(pack_dir).items() if f"{bothy_packs.PACK_FILES}/{name}" in private}
    if documents:
        path = os.path.join(pack_dir, "sources.json")
        srcs = _read(path, {})
        for key in ("sources", "verificationSources"):
            for item in srcs.get(key, []):
                for field, value in list(item.items()):
                    if isinstance(value, str) and value in documents:
                        item[field] = ""
        _write(path, srcs)
    if meta.get("kind") == "medical":
        visuals = _read(os.path.join(pack_dir, "visuals.json"), [])
        gone = set()
        for v in visuals:
            files = [f"images/{v[k]}" for k in ("image", "thumb") if v.get(k)]
            if any(f in private for f in files):
                gone.add(v["id"])
        _write(os.path.join(pack_dir, "visuals.json"), [v for v in visuals if v["id"] not in gone])
        for pid in meta.get("protocolOrder", []):
            path = os.path.join(pack_dir, "protocols", pid, "protocol.json")
            p = _read(path)
            if any(x in gone for x in p.get("visuals", [])):
                p["visuals"] = [x for x in p["visuals"] if x not in gone]
                _write(path, p)
        report["leftOutFigures"] = len(gone)
    else:
        for cat in meta.get("categoryOrder", []):
            cdir = os.path.join(pack_dir, cat)
            info = _read(os.path.join(cdir, "category.json"))
            mapping = bothy_packs.category_images(cdir)
            urls = {url for url, name in mapping.items() if f"{cat}/{CATEGORY_IMAGES}/{name}" in private}
            if urls:
                rest = {k: v for k, v in info.items() if k not in ("fieldOrder", "guideOrder")}
                cleaned = _drop_urls(rest, urls)
                _write(os.path.join(cdir, "category.json"), {**cleaned, "fieldOrder": info["fieldOrder"],
                                                              "guideOrder": info["guideOrder"]})
            for gid in info.get("guideOrder", []):
                gdir = os.path.join(cdir, gid)
                structure = _read(os.path.join(gdir, "guide.json"))
                drop = [i for i, f in enumerate(structure.get("figures", [])) if f"{cat}/{gid}/{f['file']}" in private]
                if not drop:
                    continue
                texts = {lang: open(os.path.join(gdir, f"guide.{lang}.md"), encoding="utf-8").read()
                         for lang in bothy_packs.LANGS}
                guide = bothy_packs.files_to_guide(structure, texts, lambda fig: fig["file"])
                guide["figures"] = [f for i, f in enumerate(guide["figures"]) if i not in drop]
                new_structure, new_texts = bothy_packs.guide_to_files(guide, os.path.basename)
                for key in ("review",):
                    if key in structure:
                        new_structure[key] = structure[key]
                for old, new in zip([f for i, f in enumerate(structure["figures"]) if i not in drop], new_structure["figures"]):
                    new["src"] = old.get("src", new["src"])
                _write(os.path.join(gdir, "guide.json"), new_structure)
                for lang, text in new_texts.items():
                    with open(os.path.join(gdir, f"guide.{lang}.md"), "w", encoding="utf-8") as fh:
                        fh.write(text)
    for rel, pic in private.items():
        path = os.path.join(pack_dir, rel)
        os.remove(path)
        side = os.path.splitext(path)[0] + ".json"
        if os.path.exists(side):
            os.remove(side)
        removed.append({"file": rel, "licence": pic["licence"]})


def export(pack_dir, out_dir, *, categories=None, guides=None, shareable=False, new_id=None, title=None,
           text_licence=None, authors=None, shared_version=None):
    """Write a pack file into out_dir and return a report: {"file", "name", "size", "summary", "leftOut"}.

    categories / guides narrow the export to some categories, or single guides given as "category/guide".
    shareable leaves out what may not be shared; it needs an open licence for the texts (the pack's, or
    text_licence when the person exporting may give one)."""
    meta = _read(os.path.join(pack_dir, "pack.json"))
    pack_id = new_id or meta["id"]
    if not SLUG.match(pack_id):
        raise PackError(f"the pack id {pack_id!r} may use lowercase letters, digits and hyphens only")
    if (categories or guides) and meta.get("kind") != "knowledge":
        raise PackError("only knowledge packs can be exported in parts")
    licence = text_licence or meta.get("licence", "")
    if shareable and not is_open(licence):
        raise PackError("a shareable pack needs an open licence for its texts (CC BY-SA 4.0, CC BY 4.0 or CC0); "
                        f"this pack's texts are marked {licence or 'without a licence'}")
    report = {"leftOut": []}
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".export-", dir=out_dir)
    try:
        dest = os.path.join(work, pack_id)
        if meta.get("kind") == "knowledge":
            _copy_selection(pack_dir, dest, categories, guides)
        else:
            shutil.copytree(pack_dir, dest, ignore=shutil.ignore_patterns("*.tmp", ".*"))
        new_meta = _read(os.path.join(dest, "pack.json"))
        new_meta["id"] = pack_id
        if title:
            new_meta["title"] = {"en": title, "de": title}
        if authors:
            new_meta["authors"] = authors
        new_meta["licence"] = licence
        new_meta.pop("readOnly", None)
        new_meta.pop("origin", None)
        new_meta["exported"] = _now()
        if shareable:
            new_meta["private"] = False
            new_meta["distribution"] = "shared"
            if shared_version:
                new_meta["version"] = shared_version
            _write(os.path.join(dest, "pack.json"), new_meta)
            _make_shareable(dest, report)
        else:
            _write(os.path.join(dest, "pack.json"), new_meta)
        _validate(dest)  # what we write must import again
        name = f"{pack_id}-{new_meta.get('version', '1.0.0')}{'' if shareable else '-backup'}{SUFFIX}"
        target = os.path.join(out_dir, name)
        tmp = target + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, dirs, files in os.walk(dest):
                dirs.sort()
                for fname in sorted(files):
                    full = os.path.join(root, fname)
                    arc = os.path.relpath(full, work).replace(os.sep, "/")
                    if fname.lower().endswith((".webp", ".png", ".jpg", ".jpeg", ".gif")):
                        zf.write(full, arc, compress_type=zipfile.ZIP_STORED)  # already compressed
                    else:
                        zf.write(full, arc)
        os.replace(tmp, target)
        report.update({"file": target, "name": name, "size": os.path.getsize(target), "summary": summary(dest),
                       "shareable": shareable})
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Import -----------------------------------------------------------------------------------------------------

def _check_picture(path):
    lower = path.lower()
    data = open(path, "rb").read()
    if lower.endswith(".svg"):
        if re.search(rb"<script|\bon[a-z]+\s*=|javascript:|<foreignObject|<!ENTITY", data, re.I):
            raise PackError(f"{os.path.basename(path)}: SVG pictures can't contain scripts or entities")
        return
    if lower.endswith(".pdf"):
        if not data.startswith(b"%PDF-"):
            raise PackError(f"{os.path.basename(path)} isn't a PDF")
        return
    try:
        from PIL import Image
    except ImportError:
        return  # checked on the device, where Pillow is installed
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception:
        raise PackError(f"{os.path.basename(path)} isn't a readable picture")


def _validate(pack_dir):
    """Raise PackError unless pack_dir is a pack that compiles, with real pictures only."""
    meta = _read(os.path.join(pack_dir, "pack.json"))
    if meta.get("format") != bothy_packs.FORMAT or meta.get("kind") not in ("knowledge", "medical"):
        raise PackError(f"not a {bothy_packs.FORMAT} knowledge or medical pack")
    if not SLUG.match(str(meta.get("id", ""))):
        raise PackError("the pack id may use lowercase letters, digits and hyphens only")
    if meta["kind"] == "knowledge":
        bothy_packs.read_pack(pack_dir)
    else:
        bothy_packs.read_medical_pack(pack_dir)
    for root, _, files in os.walk(pack_dir):
        for name in files:
            path = os.path.join(root, name)
            if name.lower().endswith(LICENSED_EXT):
                _check_picture(path)
            elif name.endswith(".json"):
                _read(path)


def _safe_extract(zip_path, dest):
    """Extract a pack file into dest after checking every entry; returns the pack folder inside dest."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise PackError("this isn't a pack file (not a zip file)")
    with zf:
        infos = zf.infolist()
        if not infos:
            raise PackError("the pack file is empty")
        if len(infos) > MAX_FILES:
            raise PackError(f"the pack file holds more than {MAX_FILES} files")
        tops, total = set(), 0
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or "\\" in name or re.match(r"^[A-Za-z]:", name):
                raise PackError(f"unsafe path in the pack file: {name}")
            parts = [p for p in name.split("/") if p]
            if any(p in (".", "..") for p in parts):
                raise PackError(f"unsafe path in the pack file: {name}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackError(f"the pack file contains a link: {name}")
            tops.add(parts[0])
            if info.is_dir():
                continue
            if len(parts) < 2:
                raise PackError(f"{name}: every file must be inside the pack's folder")
            if not name.lower().endswith(ALLOWED_EXT):
                raise PackError(f"{name}: packs hold only text, JSON and pictures")
            if info.file_size > MAX_FILE:
                raise PackError(f"{name} is larger than {MAX_FILE // 1024 ** 2} MB")
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise PackError(f"{name} unpacks to an implausible size")
            total += info.file_size
        if len(tops) != 1:
            raise PackError("a pack file must hold exactly one folder, named after the pack")
        if total > MAX_TOTAL:
            raise PackError("the pack unpacks to more than 2 GB")
        top = tops.pop()
        if not SLUG.match(top):
            raise PackError(f"the pack folder {top!r} isn't a valid pack id")
        for info in infos:
            if info.is_dir():
                continue
            target = os.path.join(dest, *info.filename.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                copied = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > info.file_size:
                        raise PackError(f"{info.filename} is larger than the pack file says")
                    out.write(chunk)
        return os.path.join(dest, top)


def inspect(zip_path, packs_root, staging_root):
    """Check a pack file without installing it. Returns {"ok", "summary", "problem", "exists", "installed"}."""
    os.makedirs(staging_root, exist_ok=True)
    work = tempfile.mkdtemp(prefix="inspect-", dir=staging_root)
    try:
        folder = _safe_extract(zip_path, work)
        meta = _read(os.path.join(folder, "pack.json"))
        if meta.get("id") != os.path.basename(folder):
            raise PackError("the folder name in the pack file doesn't match its pack id")
        _validate(folder)
        out = {"ok": True, "summary": summary(folder), "shareProblems": share_problems(folder)}
        existing = os.path.join(packs_root, meta["id"])
        if os.path.exists(os.path.join(existing, "pack.json")):
            old = _read(os.path.join(existing, "pack.json"))
            out["exists"] = True
            out["installed"] = {"version": old.get("version"), "title": old.get("title"), "kind": old.get("kind")}
        return out
    except (PackError, KeyError, ValueError, OSError) as exc:
        return {"ok": False, "problem": str(exc)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install(zip_path, packs_root, staging_root, mode="new", new_id=None, keep_root=None):
    """Install a pack file. mode: "new" (the id must be free), "replace" (the pack with the same id is moved into
    keep_root), or "copy" (installed under new_id). Returns {"id", "summary", "replaced"}."""
    os.makedirs(staging_root, exist_ok=True)
    work = tempfile.mkdtemp(prefix="import-", dir=staging_root)
    try:
        folder = _safe_extract(zip_path, work)
        meta = _read(os.path.join(folder, "pack.json"))
        if meta.get("id") != os.path.basename(folder):
            raise PackError("the folder name in the pack file doesn't match its pack id")
        _validate(folder)
        pack_id = meta["id"]
        if mode == "copy":
            if not new_id or not SLUG.match(new_id):
                raise PackError("give the copy an id: lowercase letters, digits and hyphens")
            pack_id = new_id
            meta["id"] = new_id
        if meta.get("distribution") == "shared":
            meta["origin"] = {"imported": True}
        _write(os.path.join(folder, "pack.json"), meta)
        target = os.path.join(packs_root, pack_id)
        replaced = None
        if os.path.exists(target):
            if mode != "replace":
                raise PackError(f"a pack called {pack_id} is already installed")
            keep_root = keep_root or os.path.join(staging_root, "replaced")
            os.makedirs(keep_root, exist_ok=True)
            replaced = os.path.join(keep_root, f"{pack_id}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
            os.rename(target, replaced)
            kept = sorted(n for n in os.listdir(keep_root) if n.startswith(pack_id + "-"))
            for old in kept[:-3]:
                shutil.rmtree(os.path.join(keep_root, old), ignore_errors=True)
        os.makedirs(packs_root, exist_ok=True)
        shutil.move(folder, target)
        return {"id": pack_id, "summary": summary(target), "replaced": replaced}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def removable_drives(user):
    """Mounted USB sticks and cards the desktop user can reach: [{"id", "label", "path", "writable"}]."""
    import hashlib
    roots = [f"/media/{user}", f"/run/media/{user}", "/mnt"]
    try:
        root_dev = os.stat("/").st_dev
    except OSError:
        return []
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            try:
                if not os.path.isdir(path) or os.stat(path).st_dev == root_dev:
                    continue
            except OSError:
                continue
            out.append({"id": hashlib.sha256(path.encode()).hexdigest()[:16], "label": name, "path": path,
                        "writable": os.access(path, os.W_OK)})
    return out


# The community collection -------------------------------------------------------------------------------------
#
# A catalogue (catalogue.json, built by the bothy-knowledge repo) lists pack files with their version, size and
# SHA-256. Packs installed from it are read-only and remember where they came from, so updates can replace them.

CATALOGUE_FORMAT = "bothy-catalogue/1"
DEFAULT_CATALOGUE = "https://dith440.github.io/bothy-knowledge/catalogue.json"
MAX_CATALOGUE = 4 * 1024 ** 2
MAX_DOWNLOAD = 500 * 1024 ** 2
USER_AGENT = "Bothy knowledge packs"
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def version_key(text):
    m = _VERSION.match(str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def read_catalogue(url, timeout=30):
    """The packs a catalogue offers, each with an absolute "url". Entries that don't look right are skipped."""
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(MAX_CATALOGUE + 1)
    if len(raw) > MAX_CATALOGUE:
        raise PackError("the catalogue is implausibly large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PackError("the catalogue isn't valid JSON")
    if not isinstance(data, dict) or data.get("format") != CATALOGUE_FORMAT:
        raise PackError(f"not a {CATALOGUE_FORMAT} catalogue")
    packs = []
    for entry in data.get("packs", []):
        if not isinstance(entry, dict):
            continue
        ok = (SLUG.match(str(entry.get("id", ""))) and entry.get("kind") in ("knowledge", "medical")
              and _VERSION.match(str(entry.get("version", "")))
              and re.fullmatch(r"packs/[A-Za-z0-9._-]+\.zip", str(entry.get("file", "")))
              and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
              and isinstance(entry.get("size"), int) and 0 < entry["size"] <= MAX_DOWNLOAD)
        if ok:
            packs.append(dict(entry, url=urllib.parse.urljoin(url, entry["file"])))
    return {"name": data.get("name", ""), "updated": data.get("updated", ""), "url": url, "packs": packs}


def installed(packs_root):
    """{pack id: {"version", "kind", "origin"}} for the packs on the device."""
    out = {}
    for name in sorted(os.listdir(packs_root)) if os.path.isdir(packs_root) else []:
        meta = _read(os.path.join(packs_root, name, "pack.json"), {})
        if meta:
            out[name] = {"version": meta.get("version"), "kind": meta.get("kind"), "origin": meta.get("origin")}
    return out


def catalogue_status(catalogue, packs_root):
    """Each catalogue entry with "state": new, installed, update (a newer version), or taken (one of your own
    packs uses the id), and "installedVersion"."""
    have = installed(packs_root)
    out = []
    for entry in catalogue["packs"]:
        mine = have.get(entry["id"])
        if not mine:
            state = "new"
        elif not (mine.get("origin") or {}).get("catalogue"):
            state = "taken"
        elif version_key(entry["version"]) > version_key(mine.get("version")):
            state = "update"
        else:
            state = "installed"
        out.append(dict(entry, state=state, installedVersion=(mine or {}).get("version")))
    return out


def download_entry(entry, dest_dir):
    """Download one catalogue entry into dest_dir and check its size and SHA-256; returns the file's path."""
    import hashlib
    import urllib.request
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, f"{entry['id']}-{entry['version']}{SUFFIX}")
    req = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
    digest, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as response, open(target + ".part", "wb") as out:
        for block in iter(lambda: response.read(1 << 20), b""):
            done += len(block)
            if done > entry["size"]:
                break
            digest.update(block)
            out.write(block)
    if done != entry["size"] or digest.hexdigest() != entry["sha256"]:
        os.remove(target + ".part")
        raise PackError(f"the download of {entry['id']} doesn't match the catalogue (size or checksum); try again")
    os.replace(target + ".part", target)
    return target


def install_entry(catalogue_url, entry, packs_root, staging_root, keep_root=None):
    """Install or update one pack from the community collection. A pack of your own with the same id is never
    replaced. Returns install()'s result plus "updated"."""
    mine = installed(packs_root).get(entry["id"])
    if mine and not (mine.get("origin") or {}).get("catalogue"):
        raise PackError(f"one of your own packs is called {entry['id']}; rename it or remove it first")
    path = download_entry(entry, os.path.join(staging_root, "downloads"))
    try:
        result = install(path, packs_root, staging_root, mode="replace" if mine else "new", keep_root=keep_root)
    finally:
        os.remove(path)
    meta_path = os.path.join(packs_root, result["id"], "pack.json")
    meta = _read(meta_path)
    meta["readOnly"] = True
    meta["origin"] = {"catalogue": catalogue_url, "version": entry["version"], "installed": _now()}
    _write(meta_path, meta)
    result["updated"] = bool(mine)
    return result


def copy_pack(packs_root, pack_id, new_id, title=None):
    """An editable copy of a pack (for changing a community pack for yourself)."""
    if not SLUG.match(str(new_id or "")):
        raise PackError("give the copy an id: lowercase letters, digits and hyphens")
    src, dest = os.path.join(packs_root, pack_id), os.path.join(packs_root, new_id)
    if os.path.exists(dest):
        raise PackError(f"a pack called {new_id} already exists")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.tmp", ".*"))
    meta = _read(os.path.join(dest, "pack.json"))
    meta.update({"id": new_id, "private": True})
    for key in ("readOnly", "origin", "exported", "distribution"):
        meta.pop(key, None)
    if title:
        meta["title"] = {"en": title, "de": title}
    _write(os.path.join(dest, "pack.json"), meta)
    return new_id
