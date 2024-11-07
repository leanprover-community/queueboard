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

from util import eprint, parse_json_file


# Determine a PR's CI status: the return value is one of "pass", "fail" and "running".
# (Queued or waiting also count as running, cancelled CI counts as failing.)
# 'CI_check_nodes' is an array of JSON data of all checks for all the commits.
def determine_ci_status(number, CI_check_nodes: dict) -> str:
    # We consider CI to be passing if no job fails, and every job succeeds
    # or is skipped. (In the future, we may exclude inessential runs.)
    in_progress = False
    for r in CI_check_nodes:
        # Ignore bors runs: these don't contain status information (and are not interesting for us).
        if "context" in r:
            continue
        if r["conclusion"] in ["FAILURE", "CANCELLED"]:
            # Future: exclude "inessential" runs?
            return "fail"
        elif r["conclusion"] in ["SUCCESS", "SKIPPED", "NEUTRAL"]:
            continue
        elif r["conclusion"] is None and r["status"] in ["IN_PROGRESS", "QUEUED"]:
            in_progress = True
        else:
            print(f'CI run \"{r["name"]}\" for PR {number} has interesting data: {r}"')
    return "running" if in_progress else "pass"


def get_aggregate_data(pr_data: dict, only_basic_info: bool) -> dict:
    inner = pr_data["data"]["repository"]["pullRequest"]
    number = inner["number"]
    head_repo = inner["headRepositoryOwner"]
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
    files = inner["changedFiles"]
    # Names of all labels applied to this PR: missing the background colour!
    labels = [lab["name"] for lab in inner["labels"]["nodes"]]
    assignees = [ass["login"] for ass in inner["assignees"]["nodes"]]
    # Get information about the latest CI run. We just look at the "summary job".
    CI_status = determine_ci_status(number, inner["statusCheckRollup"]["contexts"]["nodes"])
    # NB. When adding future fields, pay attention to whether the 'basic' info files
    # also contain this information --- otherwise, it is fine to omit it!
    aggregate_data = {
        "number": number,
        "is_draft": is_draft,
        "CI_status": CI_status,
        "head_repo": head_repo,
        "base_branch": base_branch,
        "state": state,
        "last_updated": last_updated,
        "author": author,
        "title": title,
        "label_names": labels,
        "num_files": files,
        "additions": additions,
        "deletions": deletions,
        "assignees": assignees,
    }
    if not only_basic_info:
        number_comments = len(inner["comments"]["nodes"])
        number_review_comments = 0
        review_threads = inner["reviewThreads"]["nodes"]
        for t in review_threads:
            number_review_comments += len(t["comments"]["nodes"])
        aggregate_data["number_comments"] = number_comments
        aggregate_data["number_review_comments"] = number_review_comments
        # github usernames of everyone who left an "approving" review on this PR.
        # TODO: also collect this data for all "basic" PRs, after re-downloading their data
        approvals = []
        for r in inner["reviews"]["nodes"]:
            if r["state"] == "APPROVED":
                approvals.append(r["author"]["login"])
        aggregate_data["review_approvals"] = approvals
    return aggregate_data


def main() -> None:
    output = dict()
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output["timestamp"] = updated
    label_colours: dict[str, str] = dict()
    pr_data = []
    # A few files are known to have broken detailed information.
    # They can be found in the file "stubborn_prs.txt".
    known_erronerous: List[str] = []
    with open("stubborn_prs.txt", "r") as error_prs:
        for line in error_prs:
            if not line.startswith("--"):
                known_erronerous.append(line.rstrip())
    # Read all pr info files in the data directory.
    pr_dirs: List[str] = sorted(os.listdir("data"))
    for pr_dir in pr_dirs:
        only_basic_info = "basic" in pr_dir
        pr_number = pr_dir.removesuffix("-basic")
        filename = f"data/{pr_dir}/basic_pr_info.json" if only_basic_info else f"data/{pr_dir}/pr_info.json"
        match parse_json_file(filename, pr_number):
            case str(err):
                if pr_number not in known_erronerous:
                    print(f"attention: found an unexpected error!\n  {err}", file=sys.stderr)
            case dict(data):
                if (pr_number in known_erronerous) and not only_basic_info:
                    print(f"warning: PR {pr_number} has fine data, but is listed as erronerous: please remove it from that list", file=sys.stderr)
                label_data = data["data"]["repository"]["pullRequest"]["labels"]["nodes"]
                for lab in label_data:
                    if "color" in lab:
                        (name, colour) = (lab["name"], lab["color"])
                        if name in label_colours and colour != label_colours[name]:
                            eprint(f"warning: label {name} is assigned colours {colour} and {label_colours[name]}")
                        else:
                            label_colours[name] = colour
                pr_data.append(get_aggregate_data(data, only_basic_info))
    output["label_colours"] = dict(sorted(label_colours.items()))
    output["pr_statusses"] = pr_data
    with open("processed_data/aggregate_pr_data.json", "w") as f:
        print(json.dumps(output, indent=4), file=f)


main()
