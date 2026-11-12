#!/usr/bin/env python3
"""
Blocks patient-identifiable data from being committed or published.

Looks for
  * NHS numbers: 10 digits (optionally spaced 3-3-4) that pass the official
    modulus-11 check digit, so most random 10-digit numbers are ignored
  * "DOB: ..." / "date of birth ..." followed by a date
  * "MRN", "hospital number", "patient ID" followed by an identifier
  * data and imaging files (.csv, .xlsx, .sav, .dta, .rds, .parquet,
    .dcm, .nii, ...) unless listed in .pii-allow

It is a safety net, not a guarantee: names, addresses and free-text clinical
details cannot be detected reliably. Never put real patient data in this
repository.

A line that is a deliberate, safe example can be marked with  pii-ok
anywhere on it (for instance in a comment).

Usage
  python3 scripts/check_pii.py            scan every file tracked by git
  python3 scripts/check_pii.py --staged   scan what is about to be committed
                                          (used by the pre-commit hook)
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEXT_EXT = {".qmd", ".md", ".rmd", ".ipynb", ".yml", ".yaml", ".json", ".bib",
            ".py", ".r", ".txt", ".html", ".tex", ".csl", ".lua", ".scss", ".css", ".js"}
DATA_EXT = {".csv", ".tsv", ".xls", ".xlsx", ".sav", ".dta", ".sas7bdat", ".rds",
            ".rdata", ".rda", ".parquet", ".feather", ".sqlite", ".db",
            ".dcm", ".dicom", ".nii", ".gz", ".edf", ".hl7"}
SKIP_DIRS = {"_site", ".quarto", "node_modules"}

NHS_RE = re.compile(r"(?<![\d.])(\d{3})[ -]?(\d{3})[ -]?(\d{4})(?![\d.])")
DOB_RE = re.compile(r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth)\b\W{0,3}\d{1,4}[/\-. ]\d{1,2}", re.I)
MRN_RE = re.compile(r"\b(?:MRN|hospital\s+(?:number|no\.?)|patient\s+id|unit\s+number)\b\W{0,3}[A-Z]{0,3}\d{5,}", re.I)


def valid_nhs_number(digits: str) -> bool:
    if len(set(digits)) == 1:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:9], range(10, 1, -1)))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    return check != 10 and check == int(digits[9])


def git(*args) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def files_to_scan(staged: bool):
    if staged:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    else:
        names = git("ls-files").splitlines()
    return [n for n in names if n and not (set(Path(n).parts) & SKIP_DIRS)]


def read(name: str, staged: bool) -> str:
    if staged:
        return subprocess.run(["git", "show", f":{name}"], cwd=ROOT, capture_output=True,
                              text=True, errors="replace").stdout
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def allowed_data_files():
    f = ROOT / ".pii-allow"
    if not f.exists():
        return set()
    return {l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")}


def main():
    staged = "--staged" in sys.argv
    allow = allowed_data_files()
    problems = []

    for name in files_to_scan(staged):
        ext = Path(name).suffix.lower()
        if ext in DATA_EXT and name not in allow:
            problems.append((name, 0, f"data/imaging file ({ext}). If it is safe, add its path to .pii-allow"))
            continue
        if ext not in TEXT_EXT:
            continue
        for i, line in enumerate(read(name, staged).splitlines(), 1):
            if "pii-ok" in line:
                continue
            for m in NHS_RE.finditer(line):
                if valid_nhs_number("".join(m.groups())):
                    problems.append((name, i, f"possible NHS number: {m.group(0)}"))
            if DOB_RE.search(line):
                problems.append((name, i, "possible date of birth"))
            if MRN_RE.search(line):
                problems.append((name, i, "possible hospital/patient identifier"))

    if problems:
        print("check_pii.py: possible patient-identifiable data found:\n")
        for name, line, msg in problems:
            where = f"{name}:{line}" if line else name
            print(f"  {where}  {msg}")
        print("\nRemove it. If a match is a false alarm, add  pii-ok  to that line.")
        sys.exit(1)
    print("check_pii.py: no patient-identifiable data patterns found.")


if __name__ == "__main__":
    main()
