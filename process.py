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
import sys
from datetime import datetime, timezone
from os import listdir, path
from typing import List

from util import eprint, parse_json_file


# Determine a PR's CI status: the return value is one of "pass", "fail", "fail-inessential" and "running".
# (Queued or waiting also count as running, cancelled CI counts as failing.)
# 'CI_check_nodes' is an array of JSON data of all checks for all the commits.
def determine_ci_status(number, CI_check_nodes: dict) -> str:
    # If an inessential job fails, this is usually spurious (e.g. network issues/github rate limits)
    # or indicates a general problem with CI, and not this PR.
    # (Except when this PR modifies CI, of course: currently, we don't check for this.)
    inessential_jobs = [
        "label-new-contributor",
        "label-and-report-new-contributor",
        "New Contributor Check",
        "Add delegated label",
        "Add topic label",
        "apply_one_t_label",
        "Add ready-to-merge label",
        "Add ready-to-merge or delegated label",
        "Ping maintainers on Zulip",
        # This was an old name for the "Post or update summary comment" job, which has since been given a name.
        # Recall that this check looks at names of CI *jobs*, not *workflow steps*.
        "post-or-update-summary-comment",
        "build",
        "Cross off linked issues",
    ]
    # We consider CI to be passing if no job fails, and every job succeeds or is skipped.
    # If no job fails, but some are still running, we return "running".
    # If some job fails, we check if this is an inessential job or not.
    in_progress = False
    inessential_failure = False
    for r in CI_check_nodes:
        # Ignore bors runs: these don't contain status information (and are not interesting for us).
        if "context" in r:
            continue
        if "label" in r["name"] and r["name"] not in inessential_jobs:
            print(f"info: job name {r['name']} contains the word label, but is not listed as inessential")
        if r["conclusion"] in ["FAILURE", "CANCELLED"]:
            if r["name"] not in inessential_jobs:
                return "fail"
            inessential_failure = True
        elif r["conclusion"] in ["SUCCESS", "SKIPPED", "NEUTRAL"]:
            continue
        elif r["conclusion"] is None and r["status"] in ["IN_PROGRESS", "QUEUED"]:
            in_progress = True
        else:
            print(f'CI run "{r["name"]}" for PR {number} has interesting data: {r}"')
    if inessential_failure:
        return "fail-inessential"
    elif in_progress:
        return "running"
    else:
        return "pass"


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
    number_modified_files = inner["changedFiles"]
    modified_files = [n["path"] for n in inner["files"]["nodes"]]
    # Names of all labels applied to this PR: missing the background colour!
    labels = [lab["name"] for lab in inner["labels"]["nodes"]]
    assignees = [ass["login"] for ass in inner["assignees"]["nodes"]]
    # Get information about the latest CI run; `None` if that information seems missing.
    if inner["statusCheckRollup"] is None:
        print(f'warning: PR {number} has missing information ("null") for CI status checks')
        CI_status = None
    else:
        CI_status = determine_ci_status(number, inner["statusCheckRollup"]["contexts"]["nodes"])
    # github usernames of everyone who left an "approving" review on this PR.
    approvals = []
    for r in inner["reviews"]["nodes"]:
        if r["state"] == "APPROVED":
            approvals.append(r["author"]["login"])

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
        "num_files": number_modified_files,
        "files": modified_files,
        "additions": additions,
        "deletions": deletions,
        "assignees": assignees,
        "review_approvals": approvals,
    }
    if not only_basic_info:
        number_comments = len(inner["comments"]["nodes"])
        number_review_comments = 0
        review_threads = inner["reviewThreads"]["nodes"]
        for t in review_threads:
            number_review_comments += len(t["comments"]["nodes"])
        aggregate_data["number_comments"] = number_comments
        aggregate_data["number_review_comments"] = number_review_comments
    return aggregate_data


def main() -> None:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    label_colours: dict[str, str] = dict()
    all_pr_data = []
    # A few files are known to have broken detailed information.
    # They can be found in the file "stubborn_prs.txt".
    known_erronerous: List[str] = []
    with open("stubborn_prs.txt", "r") as error_prs:
        for line in error_prs:
            if not line.startswith("--"):
                known_erronerous.append(line.rstrip())
    # Read all pr info files in the data directory.
    pr_dirs: List[str] = sorted(listdir("data"))
    for pr_dir in pr_dirs:
        only_basic_info = "basic" in pr_dir
        pr_number = pr_dir.removesuffix("-basic")
        filename = path.join("data", pr_dir, "basic_pr_info.json") if only_basic_info else path.join("data", pr_dir, "pr_info.json")
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
                all_pr_data.append(get_aggregate_data(data, only_basic_info))
    all_prs = {
        "timestamp": updated,
        "label_colours": dict(sorted(label_colours.items())),
        "pr_statusses": all_pr_data,
    }
    just_open_prs = {
        "timestamp": updated,
        "label_colours": dict(sorted(label_colours.items())),
        "pr_statusses": [item for item in all_pr_data if item["state"] == "open"],
    }
    # Mapping of github handles 'X', to a list of pairs `(number, state)`,
    # where `number` is a PR number assigned to `X`,
    # and `state` is the state of that PR (open/closed).
    assignments = {}
    for pr in all_pr_data:
        val = {"number": pr["number"], "state": pr["state"]}
        if pr["assignees"]:
            for name in pr["assignees"]:
                if name not in assignments:
                    assignments[name] = [val]
                else:
                    mapping = assignments[name]
                    mapping.append(val)
                    assignments[name] = mapping
    assignment_data = {
        "timestamp": updated,
        "number_all_prs": len(all_pr_data),
        "number_open_prs": len(just_open_prs["pr_statusses"]),
        "assignments": assignments
    }

    with open(path.join("processed_data", "all_pr_data.json"), "w") as f:
        print(json.dumps(all_prs, indent=4), file=f)
    with open(path.join("processed_data", "open_pr_data.json"), "w") as f:
        print(json.dumps(just_open_prs, indent=4), file=f)
    with open(path.join("processed_data", "assignment_data.json"), "w") as f:
        print(json.dumps(assignment_data, indent=4), file=f)


main()
