#!/usr/bin/env python3

"""
This script checks if all files in the `data` directory are up to date,
by comparing their time stamps with the data in the files `all-open-PRs-{1,2}.json`.

This script assumes these files exist.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple

from dateutil import parser

from util import eprint, parse_json_file


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
            _time = parser.isoparse(content)
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


# All data we are currently extracting from each PR's aggregate info.
class AggregateData(NamedTuple):
    last_updated: str
    is_CI_running: bool


# Is there valid and complete PR data for a PR numbered `number`?
# We pass in the list of all directories in the `data` dir, to avoid computing this multiple times.
def _has_valid_entries(data_dirs: List[str], number: int) -> bool:
    has_basic_dir = f"{number}-basic" in data_dirs
    has_std_dir = str(number) in data_dirs
    match (has_basic_dir, has_std_dir):
        case (True, True) | (False, False):
            return False
        case (True, False):
            expected = ["basic_pr_info.json", "timestamp.txt"]
            path = os.path.join("data", f"{number}-basic")
            files = sorted(os.listdir(path))
            return files == expected and _check_directory(path, number, files)
        case (False, True):
            expected = ["pr_info.json", "pr_reactions.json", "timestamp.txt"]
            path = os.path.join("data", str(number))
            files = sorted(os.listdir(path))
            return files == expected and _check_directory(path, number, files)
        case _:
            assert False  # unreachable


# Read the file 'missing_prs.txt', check for entries which can be removed now and writes out the updated file.
def prune_missing_prs_file() -> None:
    current_numbers: List[str] = []
    with open("missing_prs.txt", "r") as file:
        current_numbers = file.read().strip().splitlines()
    # Remove empty lines.
    current_numbers = [n for n in current_numbers if n]
    data_dirs: List[str] = sorted(os.listdir("data"))
    # For each PR number in that file, whether there is a well-formed entry for it.
    is_well_formed = {
        n: _has_valid_entries(data_dirs, int(n)) for n in current_numbers
    }
    superfluous = [n for n in current_numbers if is_well_formed[n]]
    if superfluous:
        eprint(f"{len(superfluous)} PR(s) marked as missing have present entries now, removing: {superfluous}")
    prs_to_keep = [n for n in current_numbers if not is_well_formed[n]]
    with open("missing_prs.txt", "w") as file:
        print("foo")
        file.write('\n'.join([str(n) for n in prs_to_keep]) + '\n')


# Read the last updated fields of the aggregate data file, and compare it with the
# dates from querying github.
def main() -> None:
    # "Last updated" information as returned from a fresh github query.
    current_last_updated = extract_last_update_from_input()
    # "Last updated" information as found in the aggregate data file.
    check_data_directory_contents()
    aggregate_last_updated = dict()
    with open(os.path.join("processed_data", "aggregate_pr_data.json"), "r") as aggregate_file:
        data = json.load(aggregate_file)
        for pr in data["pr_statusses"]:
            updated = pr["last_updated"]
            ci = pr["CI_status"]
            aggregate_last_updated[pr["number"]] = AggregateData(updated, ci == "running")

    # Prune superfluous entries from 'missing_prs.txt'. We conciously run this check
    # before the others, and not in the same step as downloading the missing data
    # to increase resilience against push races or other unforeseen events.
    # Any superfluous entries observed here are actually present in the repository.
    # XXX. actually, that's nonsense --- downloading missing data happens before this step. Hm... but this is fine, if committing fails, so does this update...
    prune_missing_prs_file()

    # All PRs whose aggregate data is at least 10 minutes older than github's current "last update".
    outdated_prs: List[int] = []
    missing_prs = []
    # Note that both "last updated" fields have the same format.
    for pr_number in current_last_updated:
        current_updated = parser.isoparse(current_last_updated[pr_number])
        if pr_number not in aggregate_last_updated:
            print(f'mismatch: missing data for PR {pr_number}')
            missing_prs.append(pr_number)
            continue
        aggregate_updated = parser.isoparse(aggregate_last_updated[pr_number].last_updated)

        # current_updated should be at least as new,
        # aggregate_updated is allowed to lag behind by at most 10 minutes.
        if aggregate_updated < current_updated - timedelta(minutes=10):
            delta = current_updated - aggregate_updated
            print(f'mismatch: the aggregate file for PR {pr_number} is outdated by {delta}, please re-download!')
            print(f"  the aggregate file says {aggregate_updated}, current last update is {current_updated}")
            outdated_prs.append(pr_number)

    # Also check for PRs whose aggregate data says CI is "running", but whose last update
    # was at least 60 minutes old. In that case, some data also didn't get updated.
    ci_limit = 60
    for pr_number in aggregate_last_updated:
        is_running = aggregate_last_updated[pr_number].is_CI_running
        if is_running and aggregate_updated < datetime.now(timezone.utc) - timedelta(minutes=ci_limit):
            print(f"outdated data: the aggregate data for PR {pr_number} claims CI is still running, but was last updated more than {ci_limit} minutes ago")
            outdated_prs.append(pr_number)

    # Write out the list of missing PRs.
    # XXX why not prune here? Is there some actual race to protect against?
    # TODO: skip this step if the PR is marked as stubborn/warn about this.
    if missing_prs:
        print(f"SUMMARY: found {len(missing_prs)} PR(s) whose aggregate information is missing:\n{sorted(missing_prs)}", file=sys.stderr)
        content = ""
        with open("missing_prs.txt", "r") as file:
            content = file.read()
        if not content.strip():
            # No need to shuffle this list: gather_stats.sh skips PRs with existing
            # broken data, so each PR is tried at most once anyway.
            with open("missing_prs.txt", "w") as file:
                print("bar")
                file.write('\n'.join([str(n) for n in missing_prs]) + '\n')
            print("  Scheduled all PRs for backfilling")
    if outdated_prs:
        print(f"SUMMARY: the data integrity check found {len(outdated_prs)} PRs with outdated aggregate information:\n{sorted(outdated_prs)}")
        # Batch the PRs to to re-download: write the first N PRs into redownload.txt,
        # if that file is basically empty (i.e. no other files to already handle).
        # The next run of this script will pick this up and try to download them.
        content2 = None
        with open("redownload.txt", "r") as file:
            content2 = file.readlines()
        if content2 is None:
            return
        if len(content2) != 3 and len(content2) > 1:
            return
        with open("redownload.txt", "w") as file:
            # Shuffle the list of outdated PRs, to avoid this getting stuck in a loop
            # of trying and failing to re-download the same PR over and over.
            import random
            random.shuffle(outdated_prs)
            new = ['\n'.join([str(n) for n in outdated_prs[:min(3, len(outdated_prs))]]) + '\n']
            file.writelines(new)
    else:
        print("All PR aggregate data appears up to date, congratulations!")


main()