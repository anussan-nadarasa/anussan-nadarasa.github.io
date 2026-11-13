#!/usr/bin/env python3
"""
Builds the version-by-version comparison shown at the foot of each entry.

For every entries/*/index.qmd, reads the file's committed history (following
renames) and writes _versions/FOLDER.json: one item per distinct version,
oldest first, with its commit, date, the number of words added and removed,
and a word-level comparison with the previous version as HTML.

Runs before each build (see pre-render in _quarto.yml). Only committed
versions are shown: the live site is always built from commits. Needs the
full git history; the online build fetches it.
"""

import difflib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "entries"
OUT = ROOT / "_versions"
CONTEXT = 12          # unchanged words kept either side of a change
TOKEN = re.compile(r"\n|[^\S\n]+|[^\s]+")


def git(*args, binary=False):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL,
                                   text=not binary)


def history(rel):
    """[(sha, date, path_at_that_commit)] newest first, following renames."""
    try:
        out = git("log", "--follow", "--format=\x1e%H\x1f%cI", "--name-only", "--", rel)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    items = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        head, _, names = rec.partition("\n")
        sha, date = head.split("\x1f")
        paths = [n for n in names.splitlines() if n.strip()]
        items.append((sha, date, paths[-1] if paths else rel))
    return items


def compare(old, new):
    """Word-level comparison as HTML, with long unchanged stretches folded."""
    a, b = TOKEN.findall(old), TOKEN.findall(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    parts, added, removed = [], 0, 0
    ops = sm.get_opcodes()
    for i, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            seg = a[i1:i2]
            first, last = i == 0, i == len(ops) - 1
            keep_head = 0 if first else CONTEXT * 2
            keep_tail = 0 if last else CONTEXT * 2
            if len(seg) > keep_head + keep_tail + 4:
                head = "".join(seg[:keep_head])
                tail = "".join(seg[len(seg) - keep_tail:]) if keep_tail else ""
                parts.append(html.escape(head) + '<span class="v-gap">…</span>' + html.escape(tail))
            else:
                parts.append(html.escape("".join(seg)))
            continue
        if tag in ("delete", "replace"):
            seg = "".join(a[i1:i2])
            removed += sum(1 for t in a[i1:i2] if t.strip())
            parts.append(f"<del>{html.escape(seg)}</del>")
        if tag in ("insert", "replace"):
            seg = "".join(b[j1:j2])
            added += sum(1 for t in b[j1:j2] if t.strip())
            parts.append(f"<ins>{html.escape(seg)}</ins>")
    return "".join(parts), added, removed


def build(entry):
    rel = entry.relative_to(ROOT).as_posix()
    versions, prev_text = [], None
    for sha, date, path in reversed(history(rel)):
        try:
            text = git("show", f"{sha}:{path}", binary=True).decode("utf-8", "replace")
        except subprocess.CalledProcessError:
            continue  # deleted in this commit
        if text == prev_text:
            continue
        v = {"sha": sha, "date": date, "path": path}
        if prev_text is None:
            v.update(added=len(text.split()), removed=0, html=None)
        else:
            v["html"], v["added"], v["removed"] = compare(prev_text, text)
        versions.append(v)
        prev_text = text
    return versions


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    n = 0
    for entry in sorted(ENTRIES.glob("*/index.qmd")) if ENTRIES.exists() else []:
        versions = build(entry)
        (OUT / f"{entry.parent.name}.json").write_text(json.dumps(versions), encoding="utf-8")
        n += 1
    print(f"versions.py: version history prepared for {n} entr{'y' if n == 1 else 'ies'}")


if __name__ == "__main__":
    sys.exit(main())
