#!/usr/bin/env python3
"""Checks every pack in this collection, the way a contribution is checked before it is merged.

    python3 tools/check.py [--base REF]

A pack passes when:
  - it is a valid pack that compiles, in packs/knowledge/<id>/ or packs/medical/<id>/ (folder name = pack id)
  - it holds only text, JSON, pictures and PDFs; every picture is a real picture, every PDF a real PDF, and SVGs
    carry no scripts
  - the texts, every picture and every PDF have an open licence (CC BY-SA 4.0, CC BY 4.0, CC0, public domain), and
    every picture and PDF says who made it and where it comes from
  - pack.json has a title and a description (English, German or both), a version (1.2.3) and its authors
  - pictures are at most 2 MB each, the pack at most 50 MB
  - medical packs: every protocol was reviewed by a named, qualified person
  - no guide is in two packs on the same shelf, and no two packs share an id
With --base REF (a pull request's target), a pack that changed must also have a higher version than in REF.

Exit status is the number of problems found.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
import bothy_packs  # noqa: E402
import bothy_pack_files  # noqa: E402

KINDS = ("knowledge", "medical")
MAX_PICTURE = 2 * 1024 ** 2
MAX_PACK = 50 * 1024 ** 2
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def version_key(text):
    m = VERSION.match(str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def pack_dirs():
    for kind in KINDS:
        base = os.path.join(ROOT, "packs", kind)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            path = os.path.join(base, name)
            if os.path.isdir(path):
                yield kind, name, path


def base_version(ref, kind, name):
    try:
        text = subprocess.run(["git", "show", f"{ref}:packs/{kind}/{name}/pack.json"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
        return json.loads(text).get("version")
    except (subprocess.CalledProcessError, ValueError):
        return None  # a new pack


def changed(ref, kind, name):
    out = subprocess.run(["git", "diff", "--name-only", ref, "--", f"packs/{kind}/{name}"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def check_pack(kind, name, path, args):
    problems = []
    meta_path = os.path.join(path, "pack.json")
    if not os.path.isfile(meta_path):
        return ["pack.json is missing"]
    try:
        meta = json.load(open(meta_path, encoding="utf-8"))
    except ValueError as exc:
        return [f"pack.json isn't valid JSON: {exc}"]
    if meta.get("id") != name:
        problems.append(f"the folder is called {name}, but pack.json says id {meta.get('id')!r}")
    if meta.get("kind") != kind:
        problems.append(f"this is a {meta.get('kind')} pack in packs/{kind}/")
    try:
        bothy_pack_files._validate(path)
    except (bothy_packs.PackError, ValueError, KeyError, OSError) as exc:
        problems.append(f"the pack doesn't load: {exc}")
    problems += bothy_pack_files.share_problems(path)
    for key in ("title", "description"):
        value = meta.get(key) or {}
        if not any(str(value.get(lang, "")).strip() for lang in ("en", "de")) if isinstance(value, dict) else True:
            problems.append(f"pack.json needs a {key} (in English or German)")
    if not version_key(meta.get("version")):
        problems.append(f"pack.json needs a version like 1.0.0, not {meta.get('version')!r}")
    if "minBothy" in meta and not version_key(meta.get("minBothy")):
        problems.append(f"minBothy (the oldest Bothy the pack works with) must be a version like 0.2.0, not {meta.get('minBothy')!r}")
    if not [a for a in meta.get("authors", []) if str(a).strip()]:
        problems.append("pack.json needs its authors")
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            size = os.path.getsize(full)
            total += size
            if not fname.lower().endswith(bothy_pack_files.ALLOWED_EXT):
                problems.append(f"{rel}: packs hold only text, JSON, pictures and PDFs")
            elif fname.lower().endswith(bothy_pack_files.PICTURE_EXT) and size > MAX_PICTURE:
                problems.append(f"{rel} is {size / 1e6:.1f} MB; pictures may be 2 MB at most (the Bothy editor shrinks them)")
    if total > MAX_PACK:
        problems.append(f"the pack is {total / 1e6:.0f} MB; packs may be 50 MB at most (split it)")
    if kind == "medical":
        for pid in meta.get("protocolOrder", []):
            state = json.load(open(os.path.join(path, "protocols", pid, "protocol.json"), encoding="utf-8")).get("reviewState", {})
            if state.get("state") != "reviewed" or not str(state.get("by", "")).strip():
                problems.append(f"protocol {pid}: medical protocols need a review by a named, qualified person")
    if args.base and changed(args.base, kind, name):
        old = base_version(args.base, kind, name)
        if old and version_key(meta.get("version")) and version_key(old) and version_key(meta["version"]) <= version_key(old):
            problems.append(f"the pack changed, so its version must go up (it is {meta['version']}, was {old})")
    return problems


def main():
    p = argparse.ArgumentParser(description="Check the packs in this collection.")
    p.add_argument("--base", help="git ref to compare versions with (a pull request's target)")
    args = p.parse_args()
    failures = 0
    ids, guides = {}, {}
    for kind, name, path in pack_dirs():
        problems = check_pack(kind, name, path, args)
        if name in ids:
            problems.append(f"another pack already uses the id {name} (packs/{ids[name]}/{name})")
        ids.setdefault(name, kind)
        if kind == "knowledge" and os.path.isfile(os.path.join(path, "pack.json")):
            try:
                meta = json.load(open(os.path.join(path, "pack.json"), encoding="utf-8"))
                for cat in meta.get("categoryOrder", []):
                    info = json.load(open(os.path.join(path, cat, "category.json"), encoding="utf-8"))
                    for gid in info.get("guideOrder", []):
                        key = f"{cat}/{gid}"
                        if key in guides:
                            problems.append(f"the guide {key} is already in the pack {guides[key]}; give it another id")
                        guides.setdefault(key, name)
            except (OSError, ValueError, KeyError):
                pass
        print(f"{'ok  ' if not problems else 'FAIL'}  packs/{kind}/{name}")
        for problem in problems:
            print(f"        {problem}")
        failures += len(problems)
    print(f"{len(ids)} packs, {failures} problem(s)")
    return min(failures, 100)


if __name__ == "__main__":
    sys.exit(main())
