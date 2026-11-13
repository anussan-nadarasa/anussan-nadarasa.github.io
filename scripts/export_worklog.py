#!/usr/bin/env python3
"""
Exports a project's git history as a work log for this site.

    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME
    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME --public https://github.com/OWNER/REPO
    python3 scripts/export_worklog.py PATH/TO/PROJECT NAME --release PATH/TO/PUBLIC/CLONE https://github.com/OWNER/REPO
    add  --notes PATH/TO/PROJECT/reflections  to any of these to include reflections

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

--notes DIR: reflections written in the project, one file per day.
  DIR/full/YYYY-MM-DD.md  the full reflection, which may name the topic. While
      the project is private only its fingerprint (SHA-256 of the file's exact
      bytes) and the date it was first published leave the project. Every
      fingerprint ever published is kept, so later edits are visible.
  DIR/YYYY-MM-DD.md       optional public note (a milestone), published as
      written, topic-free. DIR/.blocklist lists words or phrases that would
      give the project away; a note containing any of them is held back.
  With --release or --public, each full reflection's text is published with
  its fingerprints. If it was edited after its first fingerprint, the
  original version is recovered from the project's git history and
  published alongside it, so both can be checked.

A log whose commits have not changed is left untouched, so nothing is pushed
on days without new work.

The fingerprints are what make the log checkable. If the project's history
is later published unchanged, anyone can confirm the commits match. Keep
patient data and anything sensitive out of the project's git history from
the start (the project starter does this), so that it can be.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent


def die(msg):
    sys.exit(f"export_worklog.py: {msg}")


NOTE_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md")
NOTE_MAX = 1200


def read_notes(folder):
    """Optional public notes (DIR/YYYY-MM-DD.md), minus any containing a
    blocked word or phrase."""
    block_file = folder / ".blocklist"
    blocked = []
    if block_file.exists():
        for line in block_file.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                blocked.append(re.compile(r"(?<![\w-])" + re.escape(w) + r"(?:s|es)?(?![\w-])", re.I))
    notes = []
    for f in sorted(folder.iterdir()):
        m = NOTE_FILE.fullmatch(f.name)
        if not m or not f.is_file():
            continue
        lines = [l.strip() for l in f.read_text(encoding="utf-8").splitlines()]
        text = " ".join(l for l in lines if l and not l.startswith("#") and not l.startswith("<!--"))
        if not text:
            continue
        if any(p.search(text) for p in blocked):
            print(f"export_worklog.py: note {m.group(1)} held back (contains a blocked word)")
            continue
        if len(text) > NOTE_MAX:
            print(f"export_worklog.py: note {m.group(1)} held back (longer than {NOTE_MAX} characters)")
            continue
        notes.append({"date": m.group(1), "text": text})
    return notes


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def find_version(project, relpath, digest):
    """Text of the version of relpath in the project's history whose
    fingerprint is digest, or None."""
    try:
        shas = subprocess.check_output(["git", "-C", str(project), "log", "--all", "--format=%H", "--", relpath],
                                       text=True).split()
    except subprocess.CalledProcessError:
        return None
    for c in shas:
        try:
            blob = subprocess.check_output(["git", "-C", str(project), "show", f"{c}:{relpath}"])
        except subprocess.CalledProcessError:
            continue
        if sha256(blob) == digest:
            return blob.decode("utf-8")
    return None


def reflections(project, folder, old, released, today):
    """Fingerprints of the full reflections (private), or their texts with
    fingerprints (released). `old` is the previous log's list."""
    prev = {r["date"]: r for r in (old or [])}
    full = folder / "full"
    files = {}
    if full.is_dir():
        for f in sorted(full.iterdir()):
            m = NOTE_FILE.fullmatch(f.name)
            if m and f.is_file():
                files[m.group(1)] = f
    out = []
    for day in sorted(set(prev) | set(files)):
        p = prev.get(day, {})
        fps = list(p.get("fingerprints", []))
        published = p.get("published", today)
        r = {"date": day, "published": published, "fingerprints": fps}
        f = files.get(day)
        if f is not None:
            data = f.read_bytes()
            h = sha256(data)
            if not released:
                if h not in fps:
                    fps.append(h)
            else:
                if len(data) > 4 * NOTE_MAX:
                    die(f"reflection {day} is longer than {4 * NOTE_MAX} characters")
                r["text"] = data.decode("utf-8")
                r["match"] = "new" if not fps else ("verified" if h == fps[0] else "revised")
                if fps and h != fps[0]:
                    rel = f.relative_to(project).as_posix()
                    orig = find_version(project, rel, fps[0])
                    if orig is not None:
                        r["original"] = orig
                    else:
                        print(f"export_worklog.py: reflection {day}: original version not found in history")
        if not r["fingerprints"] and not released:
            continue
        if not r["fingerprints"]:
            del r["published"]  # written after the last private export
        out.append(r)
    return out


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
    notes_dir = None
    if "--notes" in args:
        i = args.index("--notes")
        if i + 1 >= len(args):
            die("--notes needs the path to the reflections folder")
        notes_dir = Path(args[i + 1]).resolve()
        del args[i:i + 2]
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
    dest = SITE / "worklogs" / f"{name}.json"
    old = None
    if dest.exists():
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError:
            old = None
    if notes_dir and notes_dir.is_dir():
        notes = read_notes(notes_dir)
        if notes:
            log["notes"] = notes
        refl = reflections(project, notes_dir, (old or {}).get("reflections"),
                           bool(public or release), log["exported"][:10])
        if refl:
            log["reflections"] = refl
    elif old and old.get("reflections"):
        log["reflections"] = old["reflections"]  # never drop published fingerprints
    if release:
        if release["tree"] not in {c["tree"] for c in commits}:
            die("the public release's contents do not match any tracked commit. Publish exactly "
                "the files of a private commit (usually the last one), then export again.")
        log["release"] = release

    dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        if old and old.get("release") and not release:
            # Released projects are final: the nightly job must not undo the
            # release or hide the released reflections again.
            print(f"export_worklog.py: {name} has been released; {dest.relative_to(SITE)} left unchanged")
            return
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
