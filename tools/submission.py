#!/usr/bin/env python3
"""Turns a "Share guides" issue into a pull request: the robot behind the share form.

    python3 tools/submission.py                      (in GitHub Actions: reads the issue from the environment)
    python3 tools/submission.py --file PACK.zip --dry-run --author NAME --about TEXT   (try it locally)

It finds the pack file attached to the issue (only GitHub's own attachment addresses are fetched), checks it the
same way every pack here is checked, fills in what a deck can't know (the author's GitHub name, a description from
the form, a higher version when the pack is already here), and then either opens a pull request for a maintainer
to review, or writes back what has to change. Every word it writes goes to the issue as a comment.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
import bothy_pack_files  # noqa: E402
from bothy_packs import PackError  # noqa: E402

ATTACHMENT = re.compile(r"https://github\.com/(?:user-attachments/files/\d+|[\w.-]+/[\w.-]+/files/\d+)/[^\s)\]\"'<>]+?\.zip")
MAX_DOWNLOAD = 60 * 1024 ** 2


def section(body, title):
    """The text under one '### title' heading of an issue form."""
    m = re.search(r"^### " + re.escape(title) + r"\s*\n(.*?)(?=^### |\Z)", body or "", re.S | re.M)
    text = (m.group(1) if m else "").strip()
    return "" if text == "_No response_" else text


def download(url, dest, token):
    headers = {"User-Agent": "bothy-knowledge submission robot"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
        done = 0
        for block in iter(lambda: r.read(1 << 20), b""):
            done += len(block)
            if done > MAX_DOWNLOAD:
                raise PackError("the file is larger than 60 MB")
            out.write(block)


def bump(version):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", str(version or ""))
    major, minor, _ = (int(x) for x in m.groups()) if m else (1, 0, 0)
    return f"{major}.{minor + 1}.0"


def run(*cmd, check=True):
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True)


def place(zip_path, author, about):
    """Check the file and put its pack into packs/<kind>/<id>. Returns (kind, id, notes) or raises PackError."""
    stage = tempfile.mkdtemp(prefix="submission-")
    try:
        result = bothy_pack_files.inspect(zip_path, os.path.join(stage, "none"), os.path.join(stage, "inspect"))
        if not result["ok"]:
            raise PackError(result["problem"])
        if result["shareProblems"]:
            raise PackError("it isn't shareable yet:\n" + "\n".join(f"- {p}" for p in result["shareProblems"][:30]))
        kind, pack_id = result["summary"]["kind"], result["summary"]["id"]
        if kind == "medical":
            raise PackError("medical protocols need a review by a qualified person first; "
                            "please open a pull request for them instead (see CONTRIBUTING.md)")
        target_root = os.path.join(ROOT, "packs", kind)
        os.makedirs(target_root, exist_ok=True)
        notes = []
        existing = os.path.join(target_root, pack_id)
        old_version = None
        if os.path.isdir(existing):
            old_version = json.load(open(os.path.join(existing, "pack.json"), encoding="utf-8")).get("version")
            shutil.rmtree(existing)
        installed = bothy_pack_files.install(zip_path, target_root, os.path.join(stage, "install"))
        folder = os.path.join(target_root, installed["id"])
        meta_path = os.path.join(folder, "pack.json")
        meta = json.load(open(meta_path, encoding="utf-8"))
        for key in ("exported", "readOnly", "origin"):
            meta.pop(key, None)
        if not [a for a in meta.get("authors", []) if str(a).strip()] and author:
            meta["authors"] = [author]
            notes.append(f"Added {author} as the author.")
        description = meta.get("description") or {}
        if not any(str(v).strip() for v in description.values()) if isinstance(description, dict) else True:
            if about:
                text = " ".join(about.split())[:300]
                meta["description"] = {"en": text, "de": text}
                notes.append("Took the description from the form.")
        if old_version and bothy_pack_files.version_key(meta.get("version")) <= bothy_pack_files.version_key(old_version):
            meta["version"] = bump(old_version)
            notes.append(f"This pack is already here, so its version went from {old_version} to {meta['version']}.")
        with open(meta_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        return kind, pack_id, notes
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def check_all(base):
    args = [sys.executable, os.path.join(HERE, "check.py")] + (["--base", base] if base else [])
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout


def comment(issue, text, dry):
    if dry or not issue:
        print("--- comment ---\n" + text)
        return
    subprocess.run(["gh", "issue", "comment", str(issue), "--body", text], cwd=ROOT, check=False)


def main():
    p = argparse.ArgumentParser(description="Turn a Share guides issue into a pull request.")
    p.add_argument("--file", help="a local pack file instead of the issue's attachment")
    p.add_argument("--author", help="credit for the pack (default: the issue's author)")
    p.add_argument("--about", help="description (default: the form's 'What's in it')")
    p.add_argument("--dry-run", action="store_true", help="check and place the pack, but don't commit or comment")
    args = p.parse_args()
    body = os.environ.get("ISSUE_BODY", "")
    issue = os.environ.get("ISSUE_NUMBER", "")
    author = args.author or os.environ.get("ISSUE_AUTHOR", "")
    about = args.about if args.about is not None else section(body, "What's in it")
    token = os.environ.get("GH_TOKEN", "")
    work = tempfile.mkdtemp(prefix="share-")
    try:
        if args.file:
            zip_path = args.file
        else:
            urls = ATTACHMENT.findall(section(body, "The pack file") or body)
            if not urls:
                comment(issue, "Thanks! I couldn't find the pack file in your message. Please edit the issue and drag "
                               "the `.bothy-pack.zip` file Bothy made into the **The pack file** box; I'll check it again.", args.dry_run)
                return 1
            zip_path = os.path.join(work, "pack.zip")
            download(urls[0], zip_path, token)
        try:
            kind, pack_id, notes = place(zip_path, author, about)
        except (PackError, OSError, ValueError, KeyError) as exc:
            comment(issue, f"Thanks for sharing! The file can't go in yet: {exc}\n\nFix it in Bothy, share again, and edit "
                           "this issue with the new file; I'll check it again.", args.dry_run)
            return 1
        status, report = check_all(os.environ.get("BASE_REF", ""))
        if status:
            lines = [line.strip() for line in report.splitlines() if line.startswith("        ")]
            comment(issue, "Thanks for sharing! A few things need fixing first:\n\n" + "\n".join(f"- {l}" for l in lines[:30])
                    + "\n\nFix them in Bothy, share again, and edit this issue with the new file.", args.dry_run)
            return 1
        if args.dry_run:
            print(f"ok: packs/{kind}/{pack_id} passes; notes: {notes}")
            return 0
        branch = f"share/{pack_id}-issue-{issue}"
        run("git", "checkout", "-B", branch)
        run("git", "add", "-A", f"packs/{kind}/{pack_id}")
        run("git", "-c", "user.name=bothy-knowledge robot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", f"Add {pack_id} (shared in #{issue})")
        run("git", "push", "--force", "origin", branch)
        title = f"Add {pack_id} (shared in #{issue})"
        pr_body = (f"Shared by @{author} in #{issue}.\n\n" + "\n".join(f"- {n}" for n in notes) +
                   "\n\nThe checks passed. A maintainer reads the guides before merging: are the steps safe, complete and "
                   "sourced, and do both languages say the same?\n\nCloses #" + str(issue))
        pr = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", "main", "--title", title, "--body", pr_body],
                            cwd=ROOT, capture_output=True, text=True)
        if pr.returncode == 0:
            comment(issue, f"Thanks for sharing! The file passed every check. It's now waiting for a maintainer to read it: "
                           f"{pr.stdout.strip()}" + ("\n\n" + "\n".join(f"- {n}" for n in notes) if notes else ""), False)
        else:
            comment(issue, f"Thanks for sharing! The file passed every check and is on the branch `{branch}`. A maintainer "
                           "will open the pull request from there.", False)
            print(pr.stderr, file=sys.stderr)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
