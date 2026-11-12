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
  `ai`             either `none` or a block with non-empty `did` and `me`
  skills           must appear in skills.yml (warning otherwise)
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
            if ai.strip().lower() != "none":
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

    if "TODO" in yaml.safe_dump(fm):
        (errors if IN_CI else warnings).append("front matter still contains TODO")

    return errors, warnings


def main():
    skills = known_skills()
    files = sorted(ENTRIES.rglob("*.qmd")) if ENTRIES.exists() else []
    n_err = 0
    for f in files:
        errors, warnings = check(f, skills)
        rel = f.relative_to(ROOT)
        for w in warnings:
            print(f"  warning  {rel}: {w}")
        for e in errors:
            print(f"  ERROR    {rel}: {e}")
        n_err += len(errors)

    if n_err:
        print(f"\nvalidate.py: {n_err} error(s) in entry front matter. Fix them and try again.")
        sys.exit(1)
    print(f"validate.py: {len(files)} entr{'y' if len(files) == 1 else 'ies'} checked, no errors.")


if __name__ == "__main__":
    main()
