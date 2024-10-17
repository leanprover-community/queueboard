#!/usr/bin/env python3

"""
This script looks at all files in the `data` directory and creates a JSON file,
containing information about all PRs described in that directory. For each PR,
we list
- whether it's in draft stage (as opposed being marked as "ready for review")
- whether mathlib's CI passes on it
- the branch it is based on (usually "master")
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import List


def main():
    output = dict()
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output["timestamp"] = updated
    pr_data = []
    # Read all pr info files in the data directory.
    pr_names: List[str] = sorted(os.listdir("data"))
    for pr_number in pr_names:
        with open(f"data/{pr_number}/pr_info.json", "r") as fi:
            data = None
            # Handle data with errors gracefully: warn, but do not fail the script.
            try:
                data = json.load(fi)
            except json.decoder.JSONDecodeError:
                print(f"error: the pr_info file for PR {pr_number} is invalid JSON, ignoring", file=sys.stderr)
                continue
            if "errors" in data:
                print(f"warning: the data for PR {pr_number} is incomplete, ignoring", file=sys.stderr)
                continue
            elif "data" not in data:
                print(f"warning: the data for PR {pr_number} is incomplete (perhaps a time out downloading it), ignoring", file=sys.stderr)
                continue
            inner = data["data"]["repository"]["pullRequest"]
            number = inner["number"]
            base_branch = inner["baseRefName"]
            is_draft = inner["isDraft"]
            state = inner["state"].lower()
            last_updated = inner["updatedAt"]
            # We assume the author URL is determined by the github handle: in practice, it is.
            author = inner["author"]["login"]
            title = inner["title"]
            additions = inner["additions"]
            deletions = inner["deletions"]
            # Number of files modified by this PR.
            files = len(inner["files"]["nodes"])
            # Names of all labels applied to this PR: missing the background colour!
            labels = [lab["name"] for lab in inner["labels"]["nodes"]]
            assignees = [ass["login"] for ass in inner["assignees"]["nodes"]]
            CI_passes = False
            # Get information about the latest CI run. We just look at the "summary job".
            CI_runs = inner["statusCheckRollup"]["contexts"]["nodes"]
            for r in CI_runs:
                # Ignore bors runs: these don't have a job name (and are not interesting for us).
                if "context" in r:
                    pass
                elif r["name"] == "Summary":
                    CI_passes = True if r["conclusion"] == "SUCCESS" else False
            d = {
                "number": number,
                "is_draft": is_draft,
                "CI_passes": CI_passes,
                "base_branch": base_branch,
                "state": state,
                "last_updated": last_updated,
                "author": author,
                "title": title,
                "additions": additions,
                "deletions": deletions,
                "num_files": files,
                "label_names": labels,
                "assignees": assignees,
            }
            pr_data.append(d)
    output["pr_statusses"] = pr_data
    with open("processed_data/aggregate_pr_data.json", "w") as f:
        print(json.dumps(output, indent=4), file=f)


main()
