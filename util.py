#!/usr/bin/env python3

"""
This file contains various utility functions, which are needed in several otherwise unrelated scripts.
Currently, this contains the following
- a function to parse JSON files with PR info (with error handling),
- a helper for comparing lists of PR numbers (with detailed information about the differences)
- a function to format a |relativedelta|
"""

import json
import sys
from typing import List
from dateutil import relativedelta


def eprint(val):
    print(val, file=sys.stderr)


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


def format_delta(delta: relativedelta.relativedelta) -> str:
    def pluralize(n: int, s: str) -> str:
        return f"{n} {s}" if n == 1 else f"{n} {s}s"
    if delta.years > 0:
        return pluralize(delta.years, "year")
    elif delta.months > 0:
        return pluralize(delta.months, "month")
    elif delta.days > 0:
        return pluralize(delta.days, "day")
    elif delta.hours > 0:
        return pluralize(delta.hours, "hour")
    elif delta.minutes > 0:
        return pluralize(delta.minutes, "minute")
    else:
        return pluralize(delta.seconds, "second")
