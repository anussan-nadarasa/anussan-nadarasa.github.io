#!/usr/bin/env python3
"""
Builds the version-by-version comparison shown at the foot of each entry.

For every entries/*/index.qmd, reads the file's committed history (following
renames) and writes _versions/FOLDER.json: one item per version whose text
(the body, not the header) changed,
oldest first, with
  - its commit, date, and the number of words of text added and removed;
  - `html`: a word-level comparison of the text with the previous version;
  - `body`: the version's text rendered to HTML, for the slider;
  - `changes`: that text with the paragraphs added since the previous version
    highlighted and those removed struck through.
Everything is prepared here, at build time: the page makes no requests to
GitHub, so it keeps working if GitHub is unavailable.

Runs before each build (see pre-render in _quarto.yml). Only committed
versions are shown: the live site is always built from commits. Needs the
full git history; the online build fetches it.
"""

import difflib
import hashlib
import html
from html.parser import HTMLParser
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


def chunks(a, b):
    """Opcodes merged into readable chunks: short unchanged stretches between
    two changes (a few words such as "the" or "and") are folded into the
    change, so a rewritten phrase reads as old phrase, then new phrase."""
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    out = []  # [tag, a_tokens, b_tokens]
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        seg = [tag, a[i1:i2], b[j1:j2]]
        words = sum(1 for t in seg[1] if t.strip())
        between = 0 < k < len(ops) - 1
        if tag == "equal" and between and words <= 3 and "\n" not in seg[1]:
            seg[0] = "change"
        elif tag != "equal":
            seg[0] = "change"
        if out and out[-1][0] == "change" and seg[0] == "change":
            out[-1][1] += seg[1]; out[-1][2] += seg[2]
        else:
            out.append(seg)
    return out


def compare(old, new):
    """Word-level comparison as HTML, with long unchanged stretches folded."""
    a, b = TOKEN.findall(old), TOKEN.findall(new)
    parts, added, removed = [], 0, 0
    segs = chunks(a, b)
    for i, (tag, sa, sb) in enumerate(segs):
        if tag == "equal":
            first, last = i == 0, i == len(segs) - 1
            keep_head = 0 if first else CONTEXT * 2
            keep_tail = 0 if last else CONTEXT * 2
            if len(sa) > keep_head + keep_tail + 4:
                head = "".join(sa[:keep_head])
                tail = "".join(sa[len(sa) - keep_tail:]) if keep_tail else ""
                parts.append(html.escape(head) + '<span class="v-gap">…</span>' + html.escape(tail))
            else:
                parts.append(html.escape("".join(sa)))
            continue
        old_t, new_t = "".join(sa), "".join(sb)
        removed += sum(1 for t in sa if t.strip())
        added += sum(1 for t in sb if t.strip())
        if old_t.strip():
            parts.append(f"<del>{html.escape(old_t)}</del>")
        if new_t.strip():
            parts.append(f"<ins>{html.escape(new_t)}</ins>")
        elif not old_t.strip():
            parts.append(html.escape(new_t))
    return "".join(parts), added, removed


FRONT = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
_render_cache = {}


def render(markdown):
    """Body text of a version as HTML, via the pandoc that comes with Quarto."""
    body = FRONT.sub("", markdown, count=1)
    key = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if key in _render_cache:
        return _render_cache[key]
    cmd_base = ["-f", "markdown", "-t", "html", "--citeproc",
                "--bibliography", str(ROOT / "references.bib"), "--csl", str(ROOT / "vancouver.csl")]
    out = None
    for cmd in (["quarto", "pandoc"], ["pandoc"]):
        try:
            out = subprocess.run(cmd + cmd_base, input=body, capture_output=True, text=True,
                                 cwd=ROOT, check=True).stdout
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    if out is None:
        out = "<pre>" + html.escape(body) + "</pre>"
    _render_cache[key] = out
    return out


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Blocks(HTMLParser):
    """Splits HTML into its top-level elements."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text, self.depth, self.start, self.blocks = text, 0, None, []
        self.line_starts = [0]
        for m in re.finditer("\n", text):
            self.line_starts.append(m.end())

    def _offset(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if self.depth == 0:
                end = self.text.index(">", self._offset()) + 1
                self.blocks.append(self.text[self._offset():end])
            return
        if self.depth == 0:
            self.start = self._offset()
        self.depth += 1

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        self.depth -= 1
        if self.depth == 0 and self.start is not None:
            end = self.text.index(">", self._offset()) + 1
            self.blocks.append(self.text[self.start:end])
            self.start = None


def blocks(html_text):
    p = _Blocks(html_text)
    p.feed(html_text)
    p.close()
    return p.blocks or [html_text]


def block_changes(old_html, new_html):
    """New version's text, with added blocks marked and removed ones kept, struck through."""
    a, b = blocks(old_html), blocks(new_html)
    norm = lambda x: re.sub(r"\s+", " ", x).strip()
    sm = difflib.SequenceMatcher(None, [norm(x) for x in a], [norm(x) for x in b], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(b[j1:j2])
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            # Same number of blocks on each side: compare them pair by pair,
            # so a list that gained an item shows just that item.
            for x, y in zip(a[i1:i2], b[j1:j2]):
                merged = list_changes(x, y)
                if merged:
                    out.append(merged)
                else:
                    out.append(f'<div class="v-del">{x}</div>')
                    out.append(f'<div class="v-ins">{y}</div>')
            continue
        out.extend(f'<div class="v-del">{x}</div>' for x in a[i1:i2])
        out.extend(f'<div class="v-ins">{x}</div>' for x in b[j1:j2])
    return "\n".join(out)


LIST = re.compile(r"\A(<(ol|ul)\b[^>]*>)(.*)(</\2>)\Z", re.S)


def list_changes(old, new):
    """Two versions of one list: compare item by item."""
    ma, mb = LIST.match(old.strip()), LIST.match(new.strip())
    if not (ma and mb and ma.group(2) == mb.group(2)):
        return None
    ia, ib = blocks(ma.group(3)), blocks(mb.group(3))
    norm = lambda x: re.sub(r"\s+", " ", x).strip()
    sm = difflib.SequenceMatcher(None, [norm(x) for x in ia], [norm(x) for x in ib], autojunk=False)
    items = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            items.extend(ib[j1:j2]); continue
        items.extend(re.sub(r"\A<li\b", '<li class="v-del"', x) for x in ia[i1:i2])
        items.extend(re.sub(r"\A<li\b", '<li class="v-ins"', x) for x in ib[j1:j2])
    return mb.group(1) + "\n" + "\n".join(items) + "\n" + mb.group(4)


def build(entry):
    """Versions of the entry's text (the body, without the header), oldest
    first. A commit that changed only the header or the statement of AI use
    does not count as a new version here, and word counts cover the text
    alone, so the timeline matches exactly what it shows."""
    rel = entry.relative_to(ROOT).as_posix()
    versions, prev_body = [], None
    for sha, date, path in reversed(history(rel)):
        try:
            text = git("show", f"{sha}:{path}", binary=True).decode("utf-8", "replace")
        except subprocess.CalledProcessError:
            continue  # deleted in this commit
        body = FRONT.sub("", text, count=1).strip()
        if body == prev_body:
            continue
        v = {"sha": sha, "date": date, "path": path, "body": render(text)}
        if prev_body is None:
            v.update(added=len(body.split()), removed=0, html=None, changes=None)
        else:
            v["html"], v["added"], v["removed"] = compare(prev_body, body)
            v["changes"] = block_changes(versions[-1]["body"], v["body"])
        versions.append(v)
        prev_body = body
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
