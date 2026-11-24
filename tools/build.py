#!/usr/bin/env python3
"""Builds what decks download: one pack file per pack, and catalogue.json listing them.

    python3 tools/build.py [OUT_DIR] [--require-signature]        (default: dist/)

With CATALOGUE_SIGNING_KEY set (the collection's Ed25519 private key, base64; a GitHub secret), it also writes
catalogue.json.sig: Bothy refuses the collection's catalogue without a signature that matches the public key it
ships with. --require-signature (the publish workflow) stops when the key is missing instead of publishing
an unsigned catalogue.

Pack files are reproducible: the same pack always gives the same file, byte for byte, so its SHA-256 in the
catalogue only changes when the pack does. A small index.html lists the packs for people.
"""
import datetime
import hashlib
import html
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
import bothy_pack_files  # noqa: E402

KINDS = ("knowledge", "medical")
FORMAT = "bothy-catalogue/1"
STORED = (".webp", ".png", ".jpg", ".jpeg", ".gif")  # already compressed


def zip_pack(path, pack_id, target):
    """A pack file with fixed timestamps and order, so it only changes when the pack does."""
    with zipfile.ZipFile(target, "w") as zf:
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                arc = pack_id + "/" + os.path.relpath(full, path).replace(os.sep, "/")
                info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_STORED if name.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read(), compresslevel=9 if info.compress_type == zipfile.ZIP_DEFLATED else None)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sign(out, private_key):
    """Write catalogue.json.sig: the Ed25519 signature of catalogue.json's exact bytes, in base64."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key.strip(), validate=True))
    with open(os.path.join(out, "catalogue.json"), "rb") as fh:
        raw = fh.read()
    with open(os.path.join(out, "catalogue.json.sig"), "w", encoding="ascii", newline="\n") as fh:
        fh.write(base64.b64encode(key.sign(raw)).decode() + "\n")
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(f"Signed catalogue.json (public key {base64.b64encode(public).decode()})")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = os.path.abspath(args[0] if args else os.path.join(ROOT, "dist"))
    os.makedirs(os.path.join(out, "packs"), exist_ok=True)
    entries, withdrawn = [], []
    for kind in KINDS:
        base = os.path.join(ROOT, "packs", kind)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            path = os.path.join(base, name)
            gone = os.path.join(path, "withdrawn.json")
            if not os.path.isfile(os.path.join(path, "pack.json")) and os.path.isfile(gone):
                # Withdrawn: no file to download; Bothys that installed it remove it with their next update.
                meta = json.load(open(gone, encoding="utf-8"))
                withdrawn.append({"id": name, "kind": kind, "version": meta.get("version"), "title": meta.get("title"),
                                  "withdrawn": meta.get("withdrawn"), "reason": meta.get("reason", "")})
                print(f"  {name}  withdrawn ({meta.get('version')})")
                continue
            if not os.path.isfile(os.path.join(path, "pack.json")):
                continue
            meta = json.load(open(os.path.join(path, "pack.json"), encoding="utf-8"))
            summary = bothy_pack_files.summary(path)
            file_name = f"{name}-{meta['version']}{bothy_pack_files.SUFFIX}"
            target = os.path.join(out, "packs", file_name)
            zip_pack(path, name, target)
            entry = {"id": name, "kind": kind, "title": meta.get("title"), "description": meta.get("description"),
                     "version": meta.get("version"), "licence": meta.get("licence"), "authors": meta.get("authors", []),
                     "pictures": summary["pictures"], "reviewed": summary.get("reviewed", 0),
                     "file": f"packs/{file_name}", "size": os.path.getsize(target), "sha256": sha256(target)}
            if meta.get("minBothy"):
                entry["minBothy"] = meta["minBothy"]  # older Bothy versions show it as "needs a newer Bothy"
            if kind == "knowledge":
                entry.update({"guides": summary["guides"], "shelves": meta.get("categoryOrder", [])})
            else:
                entry["protocols"] = summary["protocols"]
            entries.append(entry)
            print(f"  {file_name}  {entry['size'] / 1e3:.0f} kB")
    catalogue = {"format": FORMAT, "name": "Bothy community knowledge",
                 "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "packs": entries,
                 "withdrawn": withdrawn}
    with open(os.path.join(out, "catalogue.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalogue, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    rows = "".join(
        f"<tr><td><a href=\"{html.escape(e['file'])}\">{html.escape((e['title'] or {}).get('en') or e['id'])}</a><br>"
        f"<small>{html.escape((e['description'] or {}).get('en', ''))}</small></td><td>{e['kind']}</td>"
        f"<td>{e.get('guides', e.get('protocols'))}</td><td>{html.escape(e['version'])}</td><td>{html.escape(e['licence'])}</td></tr>"
        for e in entries)
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Bothy community knowledge</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:60rem;"
            "margin:2rem auto;padding:0 1rem}table{border-collapse:collapse;width:100%}td,th{padding:.5rem;border-bottom:"
            "1px solid #ddd;text-align:left;vertical-align:top}small{color:#555}</style>"
            "<h1>Bothy community knowledge</h1><p>Guides and protocols for Bothy decks. On a deck, open Knowledge, "
            "the pencil, then Import; or run <code>sudo bothy content knowledge list</code>. Machine-readable: "
            "<a href=catalogue.json>catalogue.json</a>.</p><table><tr><th>Pack</th><th>Kind</th><th>Guides</th>"
            f"<th>Version</th><th>Licence</th></tr>{rows}</table>")
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    key = os.environ.get("CATALOGUE_SIGNING_KEY", "")
    if key.strip():
        sign(out, key)
    elif "--require-signature" in sys.argv:
        print("CATALOGUE_SIGNING_KEY isn't set: Bothy would refuse an unsigned catalogue, so nothing is published.")
        return 1
    print(f"Built {len(entries)} packs into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
