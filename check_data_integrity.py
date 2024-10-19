#!/usr/bin/env python3

"""
This script checks if all files in the `data` directory are up to date,
by comparing their time stamps with the data in the files `all-open-PRs-{1,2}.json`.

This script assumes these files exist.
"""

import json
import os
import sys
from datetime import timedelta
from typing import List

from util import parse_datetime, parse_json_file


# Read the input JSON files, return a dictionary mapping each PR number
# to the (current) last update data github provides.
def extract_last_update_from_input() -> dict[int, str]:
    output = dict()
    with open("all-open-PRs-1.json", "r") as file1, open("all-open-PRs-2.json", "r") as file2:
        data = json.load(file1)
        for page in data["output"]:
            for entry in page["data"]["search"]["nodes"]:
                output[entry["number"]] = entry["updatedAt"]
        data2 = json.load(file2)
        for page in data2["output"]:
            for entry in page["data"]["search"]["nodes"]:
                output[entry["number"]] = entry["updatedAt"]
    return output


def eprint(val):
    print(val, file=sys.stderr)


# Check that a timestamp file at 'path' is well-formed;
# print errors to standard output if not.
def _check_timestamp_file(path: str) -> bool:
    is_valid = True
    with open(path, "r") as file:
        content = file.read()
        if not content.endswith('\n'):
            eprint(f'error: timestamp file at path "{path}" should end with a newline')
            is_valid = False
        content = content.removesuffix("\n")
        if "\n" in content:
            eprint(f'error: timestamp file at path "{path}" contains more than one line of content')
            return False
        try:
            _time = parse_datetime(content)
        except ValueError:
            eprint(f'error: timestamp file at path "{path}" does not contain a valid date and time')
            is_valid = False
    return is_valid


def _check_directory(dir: str, pr_number: int, files: List[str]) -> bool:
    is_valid = True
    for file in files:
        if file == "timestamp.txt":
            is_valid = is_valid and _check_timestamp_file(os.path.join(dir, file))
        else:
            assert file.endswith('.json')
            match parse_json_file(os.path.join(dir, file), str(pr_number)):
                case str(err):
                    eprint(err)
                    is_valid = False
                case dict(_data):
                    pass
    return is_valid


# Check the contents of the data directory; print information about errors to standard error.
# - this contains only directories of the form "PR_number" or "PR_number-basic",
# - no PR has both forms present,
# - each directory only contains the expected files, and these parse successfully.
# Return if all data was well-formed, as above.
def check_data_directory_contents() -> bool:
    is_wellformed = True
    data_dirs: List[str] = sorted(os.listdir("data"))
    for dir in data_dirs:
        if dir.endswith("-basic"):
            number = dir.removesuffix("-basic")
            if number in data_dirs:
                eprint(f"error: there is both a normal and a 'basic' data directory for PR {number}")
                is_wellformed = False
            expected = ["basic_pr_info.json", "timestamp.txt"]
            files = sorted(os.listdir(os.path.join("data", dir)))
            if files != expected:
                eprint(f"files for PR {number} did not match what I wanted: expected {expected}, got {files}")
                is_wellformed = False
                continue
            is_wellformed = is_wellformed and _check_directory(os.path.join("data", dir), int(number), files)
        elif dir.isnumeric():
            expected = ["pr_info.json", "pr_reactions.json", "timestamp.txt"]
            files = sorted(os.listdir(os.path.join("data", dir)))
            if files != expected:
                eprint(f"files for PR {dir} did not match what I wanted: expected {expected}, got {files}")
                is_wellformed = False
                continue
            is_wellformed = is_wellformed and _check_directory(os.path.join("data", dir), int(dir), files)
        else:
            eprint("error: found directory {dir}, which was unexpected")
            is_wellformed = False
    return is_wellformed


# Read the last updated fields of the aggregate data file, and compare it with the
# dates from querying github.
def main() -> None:
    current_last_updated = extract_last_update_from_input()
    check_data_directory_contents()
    aggregate_last_updated = dict()
    with open(os.path.join("processed_data", "aggregate_pr_data.json"), "r") as aggregate_file:
        data = json.load(aggregate_file)
        for pr in data["pr_statusses"]:
            aggregate_last_updated[pr["number"]] = pr["last_updated"]

    outdated_prs: List[int] = []
    N = 2
    very_outdated: List[int] = []  # larger than N days
    # Note that both "last updated" fields have the same format.
    for pr_number in current_last_updated:
        current_updated = parse_datetime(current_last_updated[pr_number])
        if pr_number not in aggregate_last_updated:
            print(f'mismatch: missing data for PR {pr_number}')
            # FIXME: backfill that one as well; skipped for now
            continue
        aggregate_updated = parse_datetime(aggregate_last_updated[pr_number])

        # current_updated should be at least as new,
        # aggregate_updated is allowed to lag behind by at most 10 minutes.
        if aggregate_updated < current_updated - timedelta(minutes=10):
            delta = current_updated - aggregate_updated
            print(f'mismatch: the aggregate file for PR {pr_number} is outdated by {delta}, please re-download!')
            print(f"  the aggregate file says {aggregate_updated}, current last update is {current_updated}")
            outdated_prs.append(pr_number)
            if delta > timedelta(days=N):
                very_outdated.append(pr_number)
    if outdated_prs:
        print(f"SUMMARY: the data integrity check found {len(outdated_prs)} PRs with outdated aggregate information:\n{sorted(outdated_prs)}")
        very_outdated = sorted(very_outdated)
        print(f"Among these, {len(very_outdated)} PRs are lagging behind by more than {N} days: {very_outdated}")
        # Batch the PRs to to re-download: write the first N PRs into redownload.txt,
        # if that file is basically empty (i.e. no other files to already handle).
        # The next run of this script will pick this up and try to download them.
        content = None
        with open("redownload.txt", "r") as file:
            content = file.readlines()
        if len(content) > 1:
            return
        with open("redownload.txt", "w") as file:
            # Shuffle the list of very outdated PRs, to avoid this getting stuck in a loop
            # of trying and failing to re-download the same PR over and over.
            import random
            random.shuffle(very_outdated)
            new = ['\n'.join([str(n) for n in very_outdated[:min(3, len(list))]]) + '\n']
            file.writelines(new)
    else:
        print("All PR aggregate data appears up to date, congratulations!")


main()