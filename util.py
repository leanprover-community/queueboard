#!/usr/bin/env python3

"""
This file contains various utility functions, which are needed in several otherwise unrelated scripts.
Currently, this contains the following
- a function to parse JSON files with PR info (with error handling),
- parsing a 'data' into a datetime
- comparing lists of PR numbers (with descriptive information)
"""

from datetime import datetime
import json
import sys
from typing import List


# Parse the JSON file 'name' for PR 'number'. Returned the parsed file if successful,
# and an error message describing what went wrong otherwise.
def parse_json_file(name: str, pr_number: str) -> dict | str:
    data = None
    with open(name, "r") as fi:
        try:
            data = json.load(fi)
        except json.decoder.JSONDecodeError:
            return f"error: the file {name} for PR {pr_number} is invalid JSON, ignoring"
    if "errors" in data:
        return f"warning: the data for PR {pr_number} is incomplete, ignoring"
    elif "data" not in data:
        return f"warning: the data for PR {pr_number} is incomplete (perhaps a time out downloading it), ignoring"
    return data


# Parse input of the form "2024-04-29T18:53:51Z" into a datetime.
# The "Z" suffix means it's a time in UTC.
def parse_datetime(rep: str) -> datetime:
    return datetime.strptime(rep, "%Y-%m-%dT%H:%M:%SZ")

assert parse_datetime("2024-04-29T18:53:51Z") == datetime(2024, 4, 29, 18, 53, 51)


# Compare two lists of PR numbers for equality, printing informative output if different.
def my_assert_eq(msg: str, left: List[int], right: List[int]) -> bool:
    if left != right:
        print(f"assertion failure comparing {msg}\n  found {len(left)} PR(s) on the left, {len(right)} PR(s) on the right", file=sys.stderr)
        left_sans_right = set(left) - set(right)
        right_sans_left = set(right) - set(left)
        if left_sans_right:
            print(f"  the following {len(left_sans_right)} PR(s) are contained in left, but not right: {sorted(left_sans_right)}", file=sys.stderr)
        if right_sans_left:
            print(f"  the following {len(right_sans_left)} PR(s) are contained in right, but not left: {sorted(right_sans_left)}", file=sys.stderr)
        return False
    return True
