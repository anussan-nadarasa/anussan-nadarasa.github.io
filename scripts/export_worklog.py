#!/usr/bin/env python3
"""
Exports a project's git history as a work log for this site.

    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME
    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME --public https://github.com/OWNER/REPO
    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME --release PATH/TO/PUBLIC/CLONE https://github.com/OWNER/REPO

Writes worklogs/NAME.json. Point an entry at it with `worklog: NAME`.

Private (default): for each commit, only its fingerprint (the full commit
hash), its time in UTC, and how many files and lines it changed. No commit
messages, file names, author names or content leave the project.

--public URL: for a project whose repository is public. Commit messages are
included and the site links every commit to its page on GitHub.

--release CLONE URL: for a private project released as a clean public
repository (a single commit, no history). Records the public commit and its
contents fingerprint (git "tree" hash). If the public files are exactly the
same as a tracked private commit, the two contents fingerprints are identical,
which anyone can check with  git rev-parse HEAD^{tree}  in a clone of the
public repository. The export refuses a release that matches no tracked commit.

Work logs are append-only: the export refuses to drop a fingerprint that has
already been published (for example after a force-push in the project).
If a project's history really had to be rewritten, export it under a new
NAME; the site's checks reject any log that loses published fingerprints.

A log whose commits have not changed is left untouched, so nothing is pushed
on days without new work.

The fingerprints are what make the log checkable. If the project's history
is later published unchanged, anyone can confirm the commits match. Keep
patient data and anything sensitive out of the project's git history from
the start (the project starter does this), so that it can be.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent


def die(msg):
    sys.exit(f"export_worklog.py: {msg}")


def main():
    args = sys.argv[1:]
    public = None
    if "--public" in args:
        i = args.index("--public")
        if i + 1 >= len(args):
            die("--public needs the repository URL")
        public = args[i + 1].rstrip("/")
        del args[i:i + 2]
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", public):
            die("--public must look like https://github.com/OWNER/REPO")
    release = None
    if "--release" in args:
        i = args.index("--release")
        if i + 2 >= len(args):
            die("--release needs the path to a clone of the public repository and its URL")
        rel_clone, rel_url = Path(args[i + 1]).resolve(), args[i + 2].rstrip("/")
        del args[i:i + 3]
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", rel_url):
            die("the release URL must look like https://github.com/OWNER/REPO")
        if not (rel_clone / ".git").exists():
            die(f"{rel_clone} is not a git repository")
        rev = lambda r: subprocess.check_output(["git", "-C", str(rel_clone), "rev-parse", r], text=True).strip()
        release = {"repo": rel_url, "commit": rev("HEAD"), "tree": rev("HEAD^{tree}")}
    if public and release:
        die("use either --public or --release, not both")
    if len(args) != 2:
        die(__doc__)

    project, name = Path(args[0]).resolve(), args[1]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        die("NAME must be lower-case letters, digits and hyphens")
    if not (project / ".git").exists():
        die(f"{project} is not a git repository")

    fmt = "%x1e%H%x1f%T%x1f%cI" + ("%x1f%s" if public else "")
    out = subprocess.check_output(
        ["git", "-C", str(project), "log", "--numstat", "--no-renames", f"--format={fmt}"],
        text=True, errors="replace")

    commits = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        parts = header.split("\x1f")
        sha, tree, date = parts[0], parts[1], parts[2]
        files = added = deleted = 0
        for line in body.splitlines():
            cols = line.split("\t")
            if len(cols) == 3:
                files += 1
                added += int(cols[0]) if cols[0].isdigit() else 0
                deleted += int(cols[1]) if cols[1].isdigit() else 0
        when = datetime.fromisoformat(date).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        c = {"sha": sha, "tree": tree, "date": when, "files": files, "added": added, "deleted": deleted}
        if public:
            c["message"] = parts[3].strip()
        commits.append(c)

    if not commits:
        die("the project has no commits yet")
    commits.sort(key=lambda c: c["date"])

    log = {
        "name": name,
        "source": "public" if public else "private",
        "exported": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commits": commits,
    }
    if public:
        log["repo"] = public
    if release:
        if release["tree"] not in {c["tree"] for c in commits}:
            die("the public release's contents do not match any tracked commit. Publish exactly "
                "the files of a private commit (usually the last one), then export again.")
        log["release"] = release

    dest = SITE / "worklogs" / f"{name}.json"
    dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError:
            old = None
        if old:
            # Append-only: every fingerprint already published must still be
            # there, with the same time and contents fingerprint. Rewritten
            # history in the project would otherwise erase published evidence.
            now = {c["sha"]: (c["date"], c.get("tree")) for c in commits}
            lost = [c["sha"][:10] for c in old.get("commits", [])
                    if c["sha"] not in now or now[c["sha"]][0] != c["date"]
                    or (c.get("tree") and now[c["sha"]][1] != c["tree"])]
            if lost:
                die(f"{len(lost)} published commit(s) are no longer in the project's history "
                    f"({', '.join(lost[:5])}{'...' if len(lost) > 5 else ''}). Work logs only grow. "
                    "If the project's history was rewritten on purpose, export it under a new name.")
        same = old is not None and \
            {k: v for k, v in old.items() if k != "exported"} == {k: v for k, v in log.items() if k != "exported"}
        if same:
            print(f"export_worklog.py: no new commits; {dest.relative_to(SITE)} left unchanged")
            return
    dest.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    print(f"export_worklog.py: {len(commits)} commits ({log['source']}) written to {dest.relative_to(SITE)}")


if __name__ == "__main__":
    main()
