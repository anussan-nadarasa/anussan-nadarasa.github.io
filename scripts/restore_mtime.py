#!/usr/bin/env python3
"""
Sets every tracked file's modification time to the time of the last commit
that changed it.

A fresh checkout (as in the online build) gives every file the same
timestamp, which would make every entry look "updated today". Quarto's
`date-modified: last-modified` reads file timestamps, so this runs first.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

out = subprocess.check_output(["git", "log", "--format=@%ct", "--name-only"], cwd=ROOT, text=True)
seen, ts = set(), None
for line in out.splitlines():
    if line.startswith("@"):
        ts = int(line[1:])
    elif line and line not in seen:
        seen.add(line)
        p = ROOT / line
        if p.exists():
            os.utime(p, (ts, ts))
print(f"restore_mtime.py: set timestamps for {len(seen)} files from git history")
