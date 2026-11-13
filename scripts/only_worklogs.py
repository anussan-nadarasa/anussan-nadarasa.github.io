#!/usr/bin/env python3
"""Decide whether a push may go live without manual review.

It may only if every file changed since the version that is currently live
is a work log (worklogs/*.json). Anything else waits for "Run workflow".

Writes `publish=true` or `publish=false` to $GITHUB_OUTPUT.
Needs GH_TOKEN and GITHUB_REPOSITORY (set in the workflow).
"""
import json
import os
import subprocess
import sys


def gh(path):
    out = subprocess.run(["gh", "api", path], check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out)


def live_sha(repo):
    """Commit of the most recent successful Pages deployment, or None."""
    deps = gh(f"repos/{repo}/deployments?environment=github-pages&per_page=30")
    for dep in deps:  # newest first
        statuses = gh(f"repos/{repo}/deployments/{dep['id']}/statuses")
        if statuses and statuses[0]["state"] == "success":
            return dep["sha"]
    return None


def decide():
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = live_sha(repo)
    if not sha:
        return False, "no live version found"
    diff = subprocess.run(["git", "diff", "--name-only", sha, "HEAD"],
                          check=True, capture_output=True, text=True).stdout.split()
    if not diff:
        return False, "nothing changed since the live version"
    others = [f for f in diff
              if not (f.startswith("worklogs/") and f.endswith(".json") and f.count("/") == 1)]
    if others:
        return False, "changes waiting for review: " + ", ".join(others)
    return True, "only work logs changed: " + ", ".join(diff)


if __name__ == "__main__":
    try:
        ok, why = decide()
    except Exception as exc:  # any doubt means no automatic publishing
        ok, why = False, f"check failed ({exc})"
    print(("Publishing automatically: " if ok else "Not publishing automatically: ") + why)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as fh:
        fh.write(f"publish={'true' if ok else 'false'}\n")
    sys.exit(0)
