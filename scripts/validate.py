#!/usr/bin/env python3
"""
Checks the front matter of every entry before the site is built.

Runs automatically before `quarto render` / `quarto preview` (pre-render in
_quarto.yml) and in the pre-commit hook. Errors stop the build; warnings
are printed and the build continues.

Rules
  all entries      title, date (YYYY-MM-DD) and a known `type`
  essay            nothing else required
  log, reflection  `ai` required; skills recommended
  project, course,
  paper            `ai`, at least one skill and at least one evidence link
  `ai`             `none`, a block with non-empty `did` and `me`, or `pending`
                   (in-progress projects with a `worklog`; no statement shown yet)
  skills           must appear in skills.yml (warning otherwise)
  worklog          must point to an existing worklogs/NAME.json; every work
                   log must match a strict schema (private logs: hashes,
                   UTC times and counts only, nothing else)
  TODO             a TODO left in a published entry is a warning on your
                   machine and an error in the online build, so a
                   half-finished entry can never go live

Usage: python3 scripts/validate.py
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("validate.py needs PyYAML:  pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "entries"
TYPES = {"log", "project", "course", "paper", "reflection", "essay"}
NEEDS_EVIDENCE = {"project", "course", "paper"}
IN_CI = os.environ.get("CI", "").lower() == "true"


def front_matter(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not m:
        return None, "no YAML front matter at the top of the file"
    try:
        return yaml.safe_load(m.group(1)) or {}, None
    except yaml.YAMLError as e:
        return None, f"front matter is not valid YAML: {e}"


def known_skills():
    f = ROOT / "skills.yml"
    if not f.exists():
        return None
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {str(s).strip() for s in data.get("skills", [])}


def check(path: Path, skills):
    errors, warnings = [], []
    fm, problem = front_matter(path)
    if problem:
        return [problem], []

    if fm.get("draft") is True:
        return [], []  # drafts are not published, so not checked

    if not fm.get("title"):
        errors.append("missing `title`")

    d = fm.get("date")
    if not isinstance(d, date):
        errors.append("`date` must be written as YYYY-MM-DD")
    else:
        prefix = path.parent.name[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", prefix) and prefix != d.isoformat():
            warnings.append(f"folder name starts {prefix} but `date` is {d.isoformat()}")

    t = fm.get("type")
    if t not in TYPES:
        errors.append(f"`type` must be one of: {', '.join(sorted(TYPES))} (got {t!r})")

    cats = fm.get("categories") or []
    if isinstance(cats, str):
        cats = [cats]

    if t and t != "essay":
        ai = fm.get("ai")
        if ai is None:
            errors.append("missing `ai` block (write `ai: none` if no AI was used)")
        elif isinstance(ai, str):
            if ai.strip().lower() == "pending":
                if not fm.get("worklog"):
                    errors.append("`ai: pending` is only for in-progress projects with a `worklog`")
            elif ai.strip().lower() != "none":
                errors.append("`ai` must be `none` or a block with `tools`, `did` and `me`")
        elif isinstance(ai, dict):
            for key in ("did", "me"):
                if not str(ai.get(key) or "").strip():
                    errors.append(f"`ai.{key}` is empty")
        else:
            errors.append("`ai` must be `none` or a block with `tools`, `did` and `me`")

        if not cats:
            (errors if t in NEEDS_EVIDENCE else warnings).append("no skills listed in `categories`")

    if t in NEEDS_EVIDENCE and not fm.get("evidence"):
        errors.append(f"a `{t}` entry needs at least one `evidence` link")

    if skills is not None:
        unknown = [c for c in cats if str(c) not in skills]
        if unknown:
            warnings.append(f"skills not in skills.yml: {', '.join(map(str, unknown))}")

    wl = fm.get("worklog")
    if wl is not None and not (ROOT / "worklogs" / f"{wl}.json").exists():
        errors.append(f"`worklog: {wl}` but worklogs/{wl}.json does not exist")

    if "TODO" in yaml.safe_dump(fm):
        (errors if IN_CI else warnings).append("front matter still contains TODO")

    return errors, warnings


SHA_RE = re.compile(r"[0-9a-f]{40}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
REPO_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")


def check_worklog(path: Path):
    """Work logs are published as-is, so allow exactly the expected fields.
    A private log may hold nothing but hashes, UTC times and counts."""
    import json
    errors = []
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        return [f"not valid JSON: {e}"]
    if not isinstance(log, dict):
        return ["must be a JSON object"]
    source = log.get("source")
    allowed = {"name", "source", "exported", "commits"} | ({"repo"} if source == "public" else {"release"})
    extra = set(log) - allowed
    if extra:
        errors.append(f"unexpected fields: {', '.join(sorted(extra))}")
    if source not in ("private", "public"):
        errors.append("`source` must be private or public")
    if log.get("name") != path.stem:
        errors.append("`name` must match the file name")
    if not DATE_RE.fullmatch(str(log.get("exported", ""))):
        errors.append("`exported` must be a UTC time")
    if source == "public" and not REPO_RE.fullmatch(str(log.get("repo", ""))):
        errors.append("a public log needs `repo` (https://github.com/OWNER/REPO)")
    commits = log.get("commits")
    if not isinstance(commits, list) or not commits:
        return errors + ["`commits` must be a non-empty list"]
    c_allowed = {"sha", "tree", "date", "files", "added", "deleted"} | ({"message"} if source == "public" else set())
    for i, c in enumerate(commits):
        if not isinstance(c, dict):
            errors.append(f"commit {i} is not an object"); continue
        extra = set(c) - c_allowed
        if extra:
            errors.append(f"commit {i}: unexpected fields {', '.join(sorted(extra))}"
                          + (" (messages are only allowed in public logs)" if "message" in extra else ""))
        if not SHA_RE.fullmatch(str(c.get("sha", ""))):
            errors.append(f"commit {i}: `sha` must be a full commit hash")
        if not SHA_RE.fullmatch(str(c.get("tree", ""))):
            errors.append(f"commit {i}: `tree` must be a full contents hash")
        if not DATE_RE.fullmatch(str(c.get("date", ""))):
            errors.append(f"commit {i}: `date` must be a UTC time")
        for k in ("files", "added", "deleted"):
            if not isinstance(c.get(k), int) or c.get(k) < 0:
                errors.append(f"commit {i}: `{k}` must be a whole number")
    rel = log.get("release")
    if rel is not None:
        if not isinstance(rel, dict) or set(rel) != {"repo", "commit", "tree"}:
            errors.append("`release` must have exactly repo, commit and tree")
        elif not (REPO_RE.fullmatch(str(rel["repo"])) and SHA_RE.fullmatch(str(rel["commit"]))
                  and SHA_RE.fullmatch(str(rel["tree"]))):
            errors.append("`release` has an invalid repo, commit or tree")
        elif rel["tree"] not in {c.get("tree") for c in commits if isinstance(c, dict)}:
            errors.append("`release` contents match no tracked commit")
    return errors


def check_worklog_history(path: Path):
    """Each committed version of a work log must keep every fingerprint of the
    version before it, unchanged. Needs the git history (the online build
    fetches all of it); skipped quietly where git is unavailable."""
    import json
    import subprocess
    rel = path.relative_to(ROOT).as_posix()
    try:
        shas = subprocess.check_output(["git", "log", "--format=%H", "--follow", "--", rel],
                                       cwd=ROOT, text=True, stderr=subprocess.DEVNULL).split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    versions = []
    for s in reversed(shas):  # oldest first
        try:
            blob = subprocess.check_output(["git", "show", f"{s}:{rel}"], cwd=ROOT, text=True,
                                           stderr=subprocess.DEVNULL)
            versions.append((s[:7], json.loads(blob)))
        except (subprocess.CalledProcessError, ValueError):
            continue
    try:
        versions.append(("working copy", json.loads(path.read_text(encoding="utf-8"))))
    except ValueError:
        pass
    errors = []
    for (a_id, a), (b_id, b) in zip(versions, versions[1:]):
        b_map = {c.get("sha"): c for c in b.get("commits", []) if isinstance(c, dict)}
        for c in a.get("commits", []):
            n = b_map.get(c.get("sha"))
            if n is None or n.get("date") != c.get("date") or (c.get("tree") and n.get("tree") != c.get("tree")):
                errors.append(f"version {b_id} dropped or changed published commit {str(c.get('sha'))[:10]} "
                              f"(present in {a_id}); work logs only grow")
                break
    return errors


def main():
    skills = known_skills()
    files = sorted(ENTRIES.rglob("*.qmd")) if ENTRIES.exists() else []
    n_err = 0

    worklogs = sorted((ROOT / "worklogs").glob("*.json")) if (ROOT / "worklogs").exists() else []
    for w in worklogs:
        for e in check_worklog(w) + check_worklog_history(w):
            print(f"  ERROR    {w.relative_to(ROOT)}: {e}")
            n_err += 1
    for f in files:
        errors, warnings = check(f, skills)
        rel = f.relative_to(ROOT)
        for w in warnings:
            print(f"  warning  {rel}: {w}")
        for e in errors:
            print(f"  ERROR    {rel}: {e}")
        n_err += len(errors)

    if n_err:
        print(f"\nvalidate.py: {n_err} error(s) in entries or work logs. Fix them and try again.")
        sys.exit(1)
    print(f"validate.py: {len(files)} entr{'y' if len(files) == 1 else 'ies'} checked, no errors.")


if __name__ == "__main__":
    main()
