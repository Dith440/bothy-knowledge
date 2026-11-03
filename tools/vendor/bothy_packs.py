"""Knowledge packs: guides as plain files that people can read, edit, review and share.

A pack is a folder:

    pack.json                       what the pack is: id, title, version, licence, authors, private or shareable
    sources.json                    the books and websites the guides cite
    <category>/category.json        name, icon, intro, sections and the order of the guides
    <category>/lexicon.json         glossary entries
    <category>/references.json      reference blocks: tables, cards, calculators
    <category>/<guide>/guide.json   the structure: ids, section, risk, figure files, source pages
    <category>/<guide>/guide.en.md  all English text, as Markdown
    <category>/<guide>/guide.de.md  all German text
    <category>/<guide>/images/      the guide's pictures, each with a .json file naming author, source and licence
    <category>/_images/             pictures the category itself shows (visual guides, knot atlas, species), same way

compile_packs() turns packs back into the content object the Knowledge pages read (KNOWLEDGE_HUB_CONTENT).
pack_from_content() does the reverse, for existing content. Converting and compiling again gives back exactly
the same object; check_round_trip() proves that for a given content object.
"""
import contextlib
import json
import os
import re
import shutil

FORMAT = "bothy-pack/1"
CATEGORY_IMAGES = "_images"  # can't clash with a guide folder: ids start with a letter or digit
IMAGE_URL = re.compile(r"^/[^\s\"]+\.(?:png|jpe?g|webp|svg|gif)$", re.I)
LANGS = ("en", "de")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Markdown section headings per language; the parser accepts either language's headings in either file.
HEADINGS = {
    "en": {"figures": "Figures", "tools": "You need", "steps": "Steps", "checks": "Check",
           "mistakes": "Common mistakes", "sourceRefs": "Source notes", "externalRefs": "Further reading",
           "parameters": "Parameters", "commands": "Commands", "actions": "Actions", "warning": "Warning"},
    "de": {"figures": "Abbildungen", "tools": "Du brauchst", "steps": "Schritte", "checks": "Prüfen",
           "mistakes": "Häufige Fehler", "sourceRefs": "Quellenhinweise", "externalRefs": "Weiterführend",
           "parameters": "Parameter", "commands": "Befehle", "actions": "Aktionen", "warning": "Warnung"},
}
HEADING_KEY = {title: key for lang in HEADINGS.values() for key, title in lang.items()}
FRONT_FIELDS = ("title", "summary", "outcome", "time", "level")


class PackError(Exception):
    pass


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _one_line(text, where):
    if "\n" in text or text != text.strip() and text.strip():
        raise PackError(f"{where}: text with line breaks or surrounding spaces can't be stored in Markdown yet")
    return text


# Guide <-> files ---------------------------------------------------------------------------------------------

def guide_to_files(guide, image_name):
    """Split one guide into (guide.json structure, {lang: markdown}). image_name maps a figure src to a file name."""
    structure = {"id": guide["id"], "fieldOrder": list(guide)}
    for key in ("sectionId", "categoryId", "risk"):
        if key in guide:
            structure[key] = guide[key]
    structure["figures"] = []
    for fig in guide.get("figures", []):
        item = {k: v for k, v in fig.items() if k not in ("alt", "legend")}
        item["file"] = "images/" + image_name(fig["src"])
        item["fieldOrder"] = list(fig)
        structure["figures"].append(item)
    structure["sourceRefs"] = [{k: v for k, v in r.items() if k != "note"} | {"fieldOrder": list(r)}
                               for r in guide.get("sourceRefs", [])]
    structure["externalRefs"] = [{k: v for k, v in r.items() if k != "note"} | {"fieldOrder": list(r)}
                                 for r in guide.get("externalRefs", [])]
    structure["commands"] = [{"code": c["code"], "fieldOrder": list(c)} for c in guide.get("commands", [])]
    structure["actions"] = [{k: v for k, v in a.items() if k != "label"} | {"fieldOrder": list(a)}
                            for a in guide.get("actions", [])]
    kw = guide.get("keywords")
    if isinstance(kw, dict):
        structure["keywordsForm"] = "languages"
    elif kw and isinstance(kw[0], dict):
        structure["keywordsForm"] = "pairs"
    elif kw is not None:
        structure["keywordsForm"] = "plain"
        structure["keywords"] = kw
    for key in ("warning", "parameters"):
        if key in guide:
            structure[key + "Order"] = list(guide[key]) if key == "warning" else [list(p) for p in guide[key]]

    texts = {}
    for lang in LANGS:
        h = HEADINGS[lang]
        where = f"{guide['id']} ({lang})"
        lines = ["---"]
        for key in FRONT_FIELDS:
            if key in guide:
                lines.append(f"{key}: {_one_line(guide[key][lang], where)}")
        if structure.get("keywordsForm") == "languages":
            lines.append("keywords: " + " | ".join(_one_line(k, where) for k in kw[lang]))
        elif structure.get("keywordsForm") == "pairs":
            lines.append("keywords: " + " | ".join(_one_line(k[lang], where) for k in kw))
        lines.append("---")
        if "warning" in guide:
            w = guide["warning"]
            lines += ["", f"> **{h['warning']}: {_one_line(w['title'][lang], where)}**", f"> {_one_line(w['text'][lang], where)}"]

        def section(key, items):
            if items:
                lines.extend(["", f"## {h[key]}", ""] + items)

        figs = []
        for i, fig in enumerate(guide.get("figures", []), 1):
            figs.append(f"{i}. ![{_one_line(fig['alt'][lang], where)}]({structure['figures'][i - 1]['file']})")
            figs += [f"   - {_one_line(x[lang], where)}" for x in fig.get("legend", [])]
        section("figures", figs)
        section("tools", [f"- {_one_line(t[lang], where)}" for t in guide.get("tools", [])])
        section("steps", [f"{i}. **{_one_line(s['title'][lang], where)}** {_one_line(s['body'][lang], where)}"
                          for i, s in enumerate(guide.get("steps", []), 1)])
        section("checks", [f"- {_one_line(t[lang], where)}" for t in guide.get("checks", [])])
        section("mistakes", [f"- {_one_line(t[lang], where)}" for t in guide.get("mistakes", [])])
        section("sourceRefs", [f"{i}. {_one_line(r['note'][lang], where)}" for i, r in enumerate(guide.get("sourceRefs", []), 1)])
        section("externalRefs", [f"{i}. {_one_line(r['note'][lang], where)}" for i, r in enumerate(guide.get("externalRefs", []), 1)])
        params = []
        for i, p in enumerate(guide.get("parameters", []), 1):
            params += [f"{i}. {_one_line(p['name'][lang], where)}", f"   - value: {_one_line(p['value'][lang], where)}",
                       f"   - meaning: {_one_line(p['meaning'][lang], where)}"]
        section("parameters", params)
        cmds = []
        for i, c in enumerate(guide.get("commands", []), 1):
            cmds += [f"{i}. {_one_line(c['title'][lang], where)}", f"   - note: {_one_line(c['note'][lang], where)}"]
        section("commands", cmds)
        section("actions", [f"{i}. {_one_line(a['label'][lang], where)}" for i, a in enumerate(guide.get("actions", []), 1)])
        texts[lang] = "\n".join(lines) + "\n"
    return structure, texts


def _parse_markdown(text):
    """Front matter dict and {section key: [lines]} from one guide.<lang>.md."""
    lines = text.split("\n")
    if lines[0] != "---":
        raise PackError("a guide file must start with a --- header")
    end = lines.index("---", 1)
    front = {}
    for line in lines[1:end]:
        key, _, value = line.partition(": ")
        front[key] = value
    sections, current, warning = {}, None, []
    for line in lines[end + 1:]:
        if line.startswith("## "):
            current = HEADING_KEY.get(line[3:].strip())
            if current is None:
                raise PackError(f"unknown section heading: {line}")
            sections[current] = []
        elif line.startswith("> ") and current is None:
            warning.append(line[2:])
        elif line and current:
            sections[current].append(line)
    return front, sections, warning


def _numbered(lines):
    """[(text after 'N. ', [sub-item lines])] from a numbered list with '   - ' sub-items."""
    items = []
    for line in lines:
        m = re.match(r"^\d+\. (.*)$", line)
        if m:
            items.append([m.group(1), []])
        elif line.startswith("   - ") and items:
            items[-1][1].append(line[5:])
        else:
            raise PackError(f"unexpected line in a numbered list: {line}")
    return items


def _bullets(lines):
    out = []
    for line in lines:
        if not line.startswith("- "):
            raise PackError(f"unexpected line in a list: {line}")
        out.append(line[2:])
    return out


def files_to_guide(structure, texts, figure_src):
    """Rebuild the guide object from guide.json and the language files. figure_src maps a figure entry to its src."""
    parsed = {lang: _parse_markdown(texts[lang]) for lang in LANGS}
    pair = lambda get: {lang: get(lang) for lang in LANGS}
    built = {}
    for key in ("sectionId", "categoryId", "risk"):
        if key in structure:
            built[key] = structure[key]
    built["id"] = structure["id"]
    for key in FRONT_FIELDS:
        if key in parsed["en"][0]:
            built[key] = pair(lambda l: parsed[l][0][key])
    if "warningOrder" in structure:
        def warn(l):
            head, text = parsed[l][2][0], parsed[l][2][1]
            label = HEADINGS[l]["warning"]
            m = re.match(r"^\*\*(?:Warning|Warnung): (.*)\*\*$", head)
            if not m:
                raise PackError(f"{structure['id']}: the warning must start with > **{label}: TITLE**")
            return m.group(1), text
        w = {lang: warn(lang) for lang in LANGS}
        parts = {"title": pair(lambda l: w[l][0]), "text": pair(lambda l: w[l][1])}
        built["warning"] = {k: parts[k] for k in structure["warningOrder"]}

    def numbered(key):
        return {l: _numbered(parsed[l][1].get(key, [])) for l in LANGS}

    if "figures" in structure["fieldOrder"]:
        figs = numbered("figures")
        out = []
        for i, meta in enumerate(structure["figures"]):
            fig = {}
            alt = {}
            for l in LANGS:
                m = re.match(r"^!\[(.*)\]\((.+)\)$", figs[l][i][0])
                alt[l] = m.group(1)
            values = {"alt": alt, "src": figure_src(meta)}
            if "legend" in meta["fieldOrder"]:
                values["legend"] = [{l: figs[l][i][1][j] for l in LANGS} for j in range(len(figs["en"][i][1]))]
            for k in meta["fieldOrder"]:
                fig[k] = values[k] if k in values else meta[k]
            out.append(fig)
        built["figures"] = out
    for key in ("tools", "checks", "mistakes"):
        if key in structure["fieldOrder"]:
            items = {l: _bullets(parsed[l][1].get(key, [])) for l in LANGS}
            built[key] = [{l: items[l][i] for l in LANGS} for i in range(len(items["en"]))]
    if "steps" in structure["fieldOrder"]:
        steps = numbered("steps")
        out = []
        for i in range(len(steps["en"])):
            title, body = {}, {}
            for l in LANGS:
                m = re.match(r"^\*\*(.*?)\*\* (.*)$", steps[l][i][0]) or re.match(r"^\*\*(.*?)\*\*()$", steps[l][i][0])
                title[l], body[l] = m.group(1), m.group(2)
            out.append({"title": title, "body": body})
        built["steps"] = [{k: s[k] for k in ("title", "body")} for s in out]
    for key in ("sourceRefs", "externalRefs"):
        if key in structure["fieldOrder"]:
            notes = numbered(key)
            out = []
            for i, meta in enumerate(structure[key]):
                values = dict(meta, note={l: notes[l][i][0] for l in LANGS})
                out.append({k: values[k] for k in meta["fieldOrder"]})
            built[key] = out
    if "parameters" in structure["fieldOrder"]:
        params = numbered("parameters")
        out = []
        for i, order in enumerate(structure["parametersOrder"]):
            sub = {l: dict(s.split(": ", 1) for s in params[l][i][1]) for l in LANGS}
            values = {"name": {l: params[l][i][0] for l in LANGS}, "value": {l: sub[l]["value"] for l in LANGS},
                      "meaning": {l: sub[l]["meaning"] for l in LANGS}}
            out.append({k: values[k] for k in order})
        built["parameters"] = out
    if "commands" in structure["fieldOrder"]:
        cmds = numbered("commands")
        out = []
        for i, meta in enumerate(structure["commands"]):
            values = {"code": meta["code"], "title": {l: cmds[l][i][0] for l in LANGS},
                      "note": {l: cmds[l][i][1][0].split(": ", 1)[1] for l in LANGS}}
            out.append({k: values[k] for k in meta["fieldOrder"]})
        built["commands"] = out
    if "actions" in structure["fieldOrder"]:
        acts = numbered("actions")
        out = []
        for i, meta in enumerate(structure["actions"]):
            values = dict(meta, label={l: acts[l][i][0] for l in LANGS})
            out.append({k: values[k] for k in meta["fieldOrder"]})
        built["actions"] = out
    form = structure.get("keywordsForm")
    if form == "plain":
        built["keywords"] = structure["keywords"]
    elif form in ("languages", "pairs"):
        kws = {l: [k for k in parsed[l][0].get("keywords", "").split(" | ") if k or parsed[l][0].get("keywords")]
               for l in LANGS}
        built["keywords"] = kws if form == "languages" else [{l: kws[l][i] for l in LANGS} for i in range(len(kws["en"]))]
    return {k: built[k] for k in structure["fieldOrder"]}


# Pack <-> content --------------------------------------------------------------------------------------------

def pack_from_content(content, out_dir, meta, copy_image, image_info):
    """Write a knowledge content object (KNOWLEDGE_HUB_CONTENT) as a pack in out_dir.

    copy_image(src, dest_path) copies a figure; image_info(src) returns the picture's metadata
    (author, source, licence). meta fills pack.json (id, title, version, licence, authors, private)."""
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise PackError(f"{out_dir} isn't empty")
    top = {k: v for k, v in content.items() if k not in ("categories", "sources", "verificationSources")}
    _write_json(os.path.join(out_dir, "pack.json"), {
        "format": FORMAT, "kind": "knowledge", **meta,
        "content": top, "contentOrder": list(content), "categoryOrder": list(content["categories"]),
    })
    _write_json(os.path.join(out_dir, "sources.json"),
                {k: content[k] for k in ("sources", "verificationSources") if k in content})
    for cat_id, cat in content["categories"].items():
        if not SLUG.match(cat_id):
            raise PackError(f"category id {cat_id!r} can't be a folder name")
        cdir = os.path.join(out_dir, cat_id)
        rest = {k: v for k, v in cat.items() if k not in ("guides", "lexicon", "references")}
        rest["fieldOrder"] = list(cat)
        rest["guideOrder"] = [g["id"] for g in cat.get("guides", [])]
        _write_json(os.path.join(cdir, "category.json"), rest)
        for key in ("lexicon", "references"):
            if key in cat:
                _write_json(os.path.join(cdir, key + ".json"), cat[key])
        for guide in cat.get("guides", []):
            if not SLUG.match(guide["id"]):
                raise PackError(f"guide id {guide['id']!r} can't be a folder name")
            gdir = os.path.join(cdir, guide["id"])
            names = {}

            def image_name(src):
                base = os.path.basename(src.split("?")[0])
                name, n = base, 2
                while name in names.values() and names.get(src) != name:
                    stem, ext = os.path.splitext(base)
                    name, n = f"{stem}-{n}{ext}", n + 1
                names[src] = name
                return name

            structure, texts = guide_to_files(guide, image_name)
            _write_json(os.path.join(gdir, "guide.json"), structure)
            for lang, text in texts.items():
                with open(os.path.join(gdir, f"guide.{lang}.md"), "w", encoding="utf-8") as fh:
                    fh.write(text)
            for fig, meta_fig in zip(guide.get("figures", []), structure["figures"]):
                dest = os.path.join(gdir, meta_fig["file"])
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                copy_image(fig["src"], dest)
                _write_json(os.path.splitext(dest)[0] + ".json", {"origin": fig["src"], **image_info(fig["src"])})
    add_category_images(out_dir, copy_image, image_info)


def _image_urls(value):
    """Picture URLs (strings like /knowledge/assets/x.svg) anywhere inside a JSON value."""
    if isinstance(value, str):
        if IMAGE_URL.match(value):
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _image_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _image_urls(item)


def _replace_urls(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, dict):
        return {k: _replace_urls(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_urls(v, mapping) for v in value]
    return value


def add_category_images(pack_dir, copy_image, image_info):
    """Copy the pictures a category itself shows into <category>/_images/, each with its .json, so the pack holds
    everything it shows. Pictures already there are skipped; returns how many were added. category.json keeps the
    original URLs; compiling points them at the copies."""
    meta = _read_json(os.path.join(pack_dir, "pack.json"))
    added = 0
    for cat_id in meta.get("categoryOrder", []):
        cdir = os.path.join(pack_dir, cat_id)
        info = _read_json(os.path.join(cdir, "category.json"))
        idir = os.path.join(cdir, CATEGORY_IMAGES)
        known = {}
        if os.path.isdir(idir):
            for name in os.listdir(idir):
                if name.endswith(".json"):
                    known[_read_json(os.path.join(idir, name)).get("origin")] = name
        used = {os.path.splitext(n)[0] for n in known.values()}
        for url in dict.fromkeys(_image_urls({k: v for k, v in info.items() if k not in ("fieldOrder", "guideOrder")})):
            if url in known:
                continue
            base = os.path.basename(url.split("?")[0])
            stem, ext = os.path.splitext(base)
            name, n = stem, 2
            while name in used:
                name, n = f"{stem}-{n}", n + 1
            used.add(name)
            os.makedirs(idir, exist_ok=True)
            copy_image(url, os.path.join(idir, name + ext))
            _write_json(os.path.join(idir, name + ".json"), {"origin": url, **image_info(url)})
            known[url] = name + ".json"
            added += 1
    return added


def category_images(cdir):
    """{original URL: file name} of a category's own pictures."""
    idir = os.path.join(cdir, CATEGORY_IMAGES)
    out = {}
    if os.path.isdir(idir):
        for name in sorted(os.listdir(idir)):
            if name.endswith(".json"):
                stem = name[:-5]
                files = [f for f in os.listdir(idir) if os.path.splitext(f)[0] == stem and not f.endswith(".json")]
                if files:
                    out[_read_json(os.path.join(idir, name)).get("origin")] = files[0]
    return out


def read_pack(pack_dir, src_mode="original", url_base=""):
    """The content object stored in one pack. src_mode 'original' gives figures their original URLs (for the
    round-trip check); 'pack' gives URLs under url_base, where the pack's images are served."""
    meta = _read_json(os.path.join(pack_dir, "pack.json"))
    if meta.get("format") != FORMAT or meta.get("kind") != "knowledge":
        raise PackError(f"{pack_dir} isn't a {FORMAT} knowledge pack")
    sources = _read_json(os.path.join(pack_dir, "sources.json"))
    categories = {}
    for cat_id in meta["categoryOrder"]:
        cdir = os.path.join(pack_dir, cat_id)
        info = _read_json(os.path.join(cdir, "category.json"))
        parts = {}
        for key in ("lexicon", "references"):
            path = os.path.join(cdir, key + ".json")
            if os.path.exists(path):
                parts[key] = _read_json(path)
        guides = []
        for gid in info["guideOrder"]:
            gdir = os.path.join(cdir, gid)
            structure = _read_json(os.path.join(gdir, "guide.json"))
            texts = {}
            for lang in LANGS:
                with open(os.path.join(gdir, f"guide.{lang}.md"), encoding="utf-8") as fh:
                    texts[lang] = fh.read()

            def figure_src(fig, gdir=gdir, cat_id=cat_id, gid=gid):
                if src_mode == "original":
                    return _read_json(os.path.splitext(os.path.join(gdir, fig["file"]))[0] + ".json")["origin"]
                return f"{url_base}/{cat_id}/{gid}/{fig['file']}"

            guides.append(files_to_guide(structure, texts, figure_src))
        parts["guides"] = guides
        rest = {k: v for k, v in info.items() if k not in ("fieldOrder", "guideOrder")}
        if src_mode == "pack":
            mapping = {url: f"{url_base}/{cat_id}/{CATEGORY_IMAGES}/{name}" for url, name in category_images(cdir).items()}
            rest = _replace_urls(rest, mapping)
        categories[cat_id] = {k: parts[k] if k in parts else rest[k] for k in info["fieldOrder"]}
    values = dict(meta["content"], categories=categories, **sources)
    return {k: values[k] for k in meta["contentOrder"]}


def compile_packs(pack_dirs, url_base=lambda pack_id: f"/knowledge/packs/{pack_id}", duplicates=None):
    """Merge several packs into one content object for the Knowledge pages. Later packs add categories and
    guides; a category that two packs share gets the guides of both, in pack order. A guide whose category and id
    an earlier pack already has is left out, and noted in duplicates (a list) when one is given."""
    merged = None
    first = {}
    for pack_dir in pack_dirs:
        pack_id = _read_json(os.path.join(pack_dir, "pack.json"))["id"]
        content = read_pack(pack_dir, src_mode="pack", url_base=url_base(pack_id))
        if merged is None:
            merged = content
            for cat_id, cat in content["categories"].items():
                for guide in cat.get("guides", []):
                    first.setdefault(f"{cat_id}/{guide['id']}", pack_id)
            continue
        for key in ("sources", "verificationSources"):
            known = {s["id"] for s in merged.get(key, [])}
            merged.setdefault(key, []).extend(s for s in content.get(key, []) if s["id"] not in known)
        for cat_id, cat in content["categories"].items():
            kept = []
            for guide in cat.get("guides", []):
                key = f"{cat_id}/{guide['id']}"
                if key in first:
                    if duplicates is not None:
                        duplicates.append({"guide": key, "shown": first[key], "hidden": pack_id})
                    continue
                first[key] = pack_id
                kept.append(guide)
            cat = dict(cat, guides=kept)
            if cat_id in merged["categories"]:
                merged["categories"][cat_id].setdefault("guides", []).extend(kept)
            else:
                merged["categories"][cat_id] = cat
                if cat_id in content.get("publishedCategoryIds", []):
                    merged.setdefault("publishedCategoryIds", []).append(cat_id)
    return merged or {"schemaVersion": 13, "release": "BOTHY_EMPTY", "publishedCategoryIds": [], "sources": [],
                      "verificationSources": [], "categories": {}}


def check_round_trip(content, pack_dir):
    """The differences between content and what pack_dir compiles back to (empty when the round trip is exact)."""
    back = read_pack(pack_dir, src_mode="original")
    problems = []

    def walk(a, b, path):
        if type(a) is not type(b):
            problems.append(f"{path}: {type(a).__name__} became {type(b).__name__}")
        elif isinstance(a, dict):
            if set(a) != set(b):
                problems.append(f"{path}: keys {sorted(a)} became {sorted(b)}")
            for k in a:
                if k in b:
                    walk(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list):
            if len(a) != len(b):
                problems.append(f"{path}: {len(a)} items became {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{path}[{i}]")
        elif a != b:
            problems.append(f"{path}: {a!r} became {b!r}")

    walk(content, back, "content")
    return problems


def diff(a, b):
    """Differences between two content objects, as readable paths (empty when they're the same data)."""
    problems = []

    def walk(x, y, path):
        if type(x) is not type(y):
            problems.append(f"{path}: {type(x).__name__} became {type(y).__name__}")
        elif isinstance(x, dict):
            if set(x) != set(y):
                problems.append(f"{path}: keys {sorted(x)} became {sorted(y)}")
            for k in x:
                if k in y:
                    walk(x[k], y[k], f"{path}.{k}")
        elif isinstance(x, list):
            if len(x) != len(y):
                problems.append(f"{path}: {len(x)} items became {len(y)}")
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f"{path}[{i}]")
        elif x != y:
            problems.append(f"{path}: {x!r} became {y!r}")

    walk(a, b, "content")
    return problems


# Medical packs -----------------------------------------------------------------------------------------------
#
#   pack.json                              kind "medical"
#   docs.json                              the guideline documents the protocols cite
#   visuals.json                           figures cut from those documents
#   protocols/<id>/protocol.json           id, icon, category, severity, sources, figures
#   protocols/<id>/protocol.<lang>.md      title, summary, red flags, steps, things to avoid
#   images/                                the figure files, each with a .json naming source and licence

MEDICAL_HEADINGS = {
    "en": {"red": "Red flags", "steps": "Steps", "avoid": "Avoid"},
    "de": {"red": "Warnzeichen", "steps": "Schritte", "avoid": "Vermeiden"},
}
MEDICAL_KEY = {title: key for lang in MEDICAL_HEADINGS.values() for key, title in lang.items()}
MEDICAL_LISTS = ("red", "steps", "avoid")


def protocol_to_files(protocol):
    structure = {k: v for k, v in protocol.items() if k not in ("title", "summary") + MEDICAL_LISTS}
    structure["fieldOrder"] = list(protocol)
    texts = {}
    for lang in LANGS:
        where = f"{protocol['id']} ({lang})"
        h = MEDICAL_HEADINGS[lang]
        lines = ["---", f"title: {_one_line(protocol['title'][lang], where)}",
                 f"summary: {_one_line(protocol['summary'][lang], where)}", "---"]
        for key in MEDICAL_LISTS:
            items = protocol.get(key, {}).get(lang, [])
            if key == "steps":
                body = [f"{i}. {_one_line(t, where)}" for i, t in enumerate(items, 1)]
            else:
                body = [f"- {_one_line(t, where)}" for t in items]
            lines += ["", f"## {h[key]}", ""] + body
        texts[lang] = "\n".join(lines) + "\n"
    return structure, texts


def files_to_protocol(structure, texts):
    values = {k: v for k, v in structure.items() if k != "fieldOrder"}
    for lang in LANGS:
        front = _parse_markdown(texts[lang].split("\n## ", 1)[0] + "\n")[0]
        lines = texts[lang].split("\n")
        current = None
        lists = {key: [] for key in MEDICAL_LISTS}
        for line in lines[lines.index("---", 1) + 1:]:
            if line.startswith("## "):
                current = MEDICAL_KEY[line[3:].strip()]
            elif line and current == "steps":
                lists["steps"].append(re.match(r"^\d+\. (.*)$", line).group(1))
            elif line and current:
                lists[current].append(_bullets([line])[0])
        for key in ("title", "summary"):
            values.setdefault(key, {})[lang] = front[key]
        for key in MEDICAL_LISTS:
            values.setdefault(key, {})[lang] = lists[key]
    return {k: values[k] for k in structure["fieldOrder"]}


def medical_pack_from_content(content, out_dir, meta, copy_image, image_info):
    """Write Medical content ({docs, visuals, protocols}) as a pack. copy_image(src, dest) copies a figure file."""
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise PackError(f"{out_dir} isn't empty")
    _write_json(os.path.join(out_dir, "pack.json"), {"format": FORMAT, "kind": "medical", **meta,
                                                      "protocolOrder": [p["id"] for p in content["protocols"]]})
    _write_json(os.path.join(out_dir, "docs.json"), content["docs"])
    _write_json(os.path.join(out_dir, "visuals.json"), content["visuals"])
    for visual in content["visuals"]:
        for key in ("image", "thumb"):
            if visual.get(key):
                dest = os.path.join(out_dir, "images", visual[key])
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                copy_image(visual[key], dest)
                _write_json(os.path.splitext(dest)[0] + ".json", {"origin": visual[key], **image_info(visual[key])})
    for protocol in content["protocols"]:
        if not SLUG.match(protocol["id"]):
            raise PackError(f"protocol id {protocol['id']!r} can't be a folder name")
        pdir = os.path.join(out_dir, "protocols", protocol["id"])
        structure, texts = protocol_to_files(protocol)
        _write_json(os.path.join(pdir, "protocol.json"), structure)
        for lang, text in texts.items():
            with open(os.path.join(pdir, f"protocol.{lang}.md"), "w", encoding="utf-8") as fh:
                fh.write(text)


def read_medical_pack(pack_dir):
    meta = _read_json(os.path.join(pack_dir, "pack.json"))
    if meta.get("format") != FORMAT or meta.get("kind") != "medical":
        raise PackError(f"{pack_dir} isn't a {FORMAT} medical pack")
    protocols = []
    for pid in meta["protocolOrder"]:
        pdir = os.path.join(pack_dir, "protocols", pid)
        texts = {}
        for lang in LANGS:
            with open(os.path.join(pdir, f"protocol.{lang}.md"), encoding="utf-8") as fh:
                texts[lang] = fh.read()
        protocols.append(files_to_protocol(_read_json(os.path.join(pdir, "protocol.json")), texts))
    return {"docs": _read_json(os.path.join(pack_dir, "docs.json")),
            "visuals": _read_json(os.path.join(pack_dir, "visuals.json")), "protocols": protocols}


def compile_medical_packs(pack_dirs, url_base=lambda pack_id: f"/knowledge/packs/{pack_id}"):
    """Merge medical packs into the content the Medical page reads; figure files get the URLs they're served at."""
    merged = {"docs": [], "visuals": [], "protocols": []}
    for pack_dir in pack_dirs:
        pack_id = _read_json(os.path.join(pack_dir, "pack.json"))["id"]
        content = read_medical_pack(pack_dir)
        for visual in content["visuals"]:
            for key in ("image", "thumb"):
                if visual.get(key):
                    visual[key] = f"{url_base(pack_id)}/images/{visual[key]}"
        for key in merged:
            known = {item["id"] for item in merged[key]}
            merged[key].extend(item for item in content[key] if item["id"] not in known)
    return merged


@contextlib.contextmanager
def _build_lock(out_dir):
    """One build at a time: the editor and bothy-knowledge-build.service may both start one."""
    os.makedirs(out_dir, exist_ok=True)
    try:
        import fcntl
    except ImportError:  # not on Linux (tests on a PC)
        yield
        return
    # Read-only, so a lock file created by root (a build run with sudo) still works for the desktop user.
    fd = os.open(os.path.join(out_dir, ".build.lock"), os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def build(packs_root, out_dir):
    """Compile every pack under packs_root into out_dir/knowledge.js and out_dir/medical.js, the files the
    Knowledge and Medical pages load. A pack that fails is reported and left out; the others still build.
    Returns the report that is also written to out_dir/build.json."""
    with _build_lock(out_dir):
        return _build(packs_root, out_dir)


def _build(packs_root, out_dir):
    found = {"knowledge": [], "medical": []}
    report = {"packs": []}
    for name in sorted(os.listdir(packs_root)) if os.path.isdir(packs_root) else []:
        pack_dir = os.path.join(packs_root, name)
        try:
            meta = _read_json(os.path.join(pack_dir, "pack.json"))
            kind = meta.get("kind")
            if kind not in found or meta.get("format") != FORMAT:
                raise PackError(f"not a {FORMAT} knowledge or medical pack")
            if meta.get("id") != name:
                raise PackError(f"the folder name must match the pack id ({meta.get('id')})")
            (read_pack if kind == "knowledge" else read_medical_pack)(pack_dir)  # parses everything once
            # Your own packs come first, so where a community pack has the same guide, yours is shown.
            found[kind].append((bool((meta.get("origin") or {}).get("catalogue")), name, pack_dir))
            report["packs"].append({"id": name, "kind": kind, "ok": True})
        except (OSError, ValueError, KeyError, PackError) as exc:
            if not os.path.isfile(os.path.join(pack_dir, "pack.json")):
                continue  # not a pack at all (a stray file or folder)
            report["packs"].append({"id": name, "ok": False, "error": str(exc)})
    for kind in found:
        found[kind] = [path for _, _, path in sorted(found[kind])]
    duplicates = []
    knowledge = compile_packs(found["knowledge"], duplicates=duplicates)
    medical = compile_medical_packs(found["medical"])
    os.makedirs(out_dir, exist_ok=True)
    for name, var, value in (("knowledge.js", "KNOWLEDGE_HUB_CONTENT", knowledge),
                             ("medical.js", "BOTHY_MEDICAL_CONTENT", medical)):
        tmp = os.path.join(out_dir, f"{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(f"window.{var}=" + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + ";\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(out_dir, name))
    report["guides"] = sum(len(c.get("guides", [])) for c in knowledge["categories"].values())
    if duplicates:
        report["duplicates"] = duplicates
    report["protocols"] = len(medical["protocols"])
    tmp = os.path.join(out_dir, f"build.json.{os.getpid()}.tmp")
    _write_json(tmp, report)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(out_dir, "build.json"))  # replaces a file from an older build whoever owned it
    return report


def js_literal(text):
    """Parse a JavaScript array or object literal (unquoted keys, single or double quotes) into Python values."""
    pos = 0
    ident = re.compile(r"[A-Za-z_$][\w$]*")
    scalar = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null")

    def skip():
        nonlocal pos
        while pos < len(text):
            if text[pos] in " \t\r\n,":
                pos += 1
            elif text.startswith("//", pos):
                pos = text.index("\n", pos)
            else:
                break

    def value():
        nonlocal pos
        skip()
        ch = text[pos]
        if ch == "{":
            pos += 1
            out = {}
            while True:
                skip()
                if text[pos] == "}":
                    pos += 1
                    return out
                if text[pos] in "'\"":
                    key = value()
                else:
                    m = ident.match(text, pos)
                    key, pos = m.group(0), m.end()
                skip()
                if text[pos] != ":":
                    raise PackError(f"expected ':' at position {pos}")
                pos += 1
                out[key] = value()
        if ch == "[":
            pos += 1
            out = []
            while True:
                skip()
                if text[pos] == "]":
                    pos += 1
                    return out
                out.append(value())
        if ch in "'\"":
            pos += 1
            buf = []
            while text[pos] != ch:
                if text[pos] == "\\":
                    nxt = text[pos + 1]
                    if nxt == "u":
                        buf.append(chr(int(text[pos + 2:pos + 6], 16)))
                        pos += 6
                        continue
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    pos += 2
                    continue
                buf.append(text[pos])
                pos += 1
            pos += 1
            return "".join(buf)
        m = scalar.match(text, pos)
        if not m:
            raise PackError(f"unexpected {text[pos:pos + 20]!r}")
        pos = m.end()
        return {"true": True, "false": False, "null": None}.get(m.group(0), None) if m.group(0) in ("true", "false", "null") \
            else json.loads(m.group(0))

    return value()


def medical_from_js(path):
    """DOCS, VISUALS and PROTOCOLS from the Medical page script (medical-v20.js)."""
    src = open(path, encoding="utf-8").read()
    out = {}
    for name, key in (("DOCS", "docs"), ("VISUALS", "visuals"), ("PROTOCOLS", "protocols")):
        start = src.index(f"  const {name} = [")
        end = src.index("\n  ];", start)
        out[key] = js_literal(src[start + len(f"  const {name} = "):end + 4])
    return out
