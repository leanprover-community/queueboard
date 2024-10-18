#!/usr/bin/env python3

"""
This script checks if all files in the `data` directory are up to date,
by comparing their time stamps with the data in the files `all-open-PRs-{1,2}.json`.

This script assumes these files exist.
"""

import json
from datetime import datetime, timedelta
from os import path


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


# Parse input of the form "2024-04-29T18:53:51Z" into a datetime.
# The "Z" suffix means it's a time in UTC.
# copied from dashboard.py
def parse_datetime(rep: str) -> datetime:
    return datetime.strptime(rep, "%Y-%m-%dT%H:%M:%SZ")


# Read the last updated fields of the aggregate data file, and compare it with the
# dates from querying github.
def main():
    current_last_updated = extract_last_update_from_input()
    aggregate_last_updated = dict()
    with open(path.join("processed_data", "aggregate_pr_data.json"), "r") as aggregate_file:
        data = json.load(aggregate_file)
        for pr in data["pr_statusses"]:
            aggregate_last_updated[pr["number"]] = pr["last_updated"]

    # Note that both "last updated" fields have the same format.
    for pr_number in current_last_updated:
        current_updated = parse_datetime(current_last_updated[pr_number])
        aggregate_updated = parse_datetime(aggregate_last_updated[pr_number])

        # current_updated should be at least as new,
        # aggregate_updated is allowed to lag behind by at most 10 minutes.
        if aggregate_updated < current_updated - timedelta(minutes=10):
            delta = current_updated - aggregate_updated
            print(f'mismatch: the aggregate file for PR {pr_number} is outdated by {delta}, please re-download!')
            print(f"aggregate file says {aggregate_updated}, current last update is {current_updated}")

    # TODO: do something with this result automatically --- e.g., schedule PRs as
    # needing downloading or a re-download.


main()