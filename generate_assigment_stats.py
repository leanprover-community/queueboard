#!/usr/bin/env python3

import json
from os import path
from typing import List, Tuple

from dashboard import _write_table_header, _write_table_row, parse_aggregate_file, pr_link, user_link, write_webpage

def main():
    with open(path.join("processed_data", "all_pr_data.json"), "r") as fi:
        parsed = parse_aggregate_file(json.load(fi))
    # We ignore all PRs whose number lies below this threshold: to avoid skewed reports from incomplete data.
    threshold = 15000
    # Collating all assigned PRs above the threshold: map each user to a tuple
    # (numbers, n_open, n_all), where
    # - numbers is a list of all open PRs that are assigned
    # - n_open is the number of open PRs assigned,
    # - n_all is the number of all PRs assigned.
    # Note that a PR assigned to several users is counted multiple times, once per assignee.

    # XXX: if this script becomes slow (so far, it doesn't), I could work in several passes:
    # first collect just all PRs with assignees, then collect more detailed stats.
    numbers: dict[str, Tuple[List[int], int, int]] = {}
    assigned_open_prs = []
    multiple_assignees = 0
    number_open_prs = 0
    items = [(number, data) for (number, data) in parsed.items() if number > threshold]
    for (pr_number, data) in items:
        if data.assignees:
            assigned_open_prs.append(pr_number)
        if data.state == 'open':
            number_open_prs += 1
        if len(data.assignees) > 1:
            multiple_assignees += 1
        for ass in data.assignees:
            if ass in numbers:
                (num, n, m) = numbers[ass]
                if data.state == 'open':
                    num.append(pr_number)
                numbers[ass] = (num, n + 1 if data.state == 'open' else n, m + 1)
            else:
                numbers[ass] = ([pr_number] if data.state == 'open' else [], 1 if data.state == 'open' else 0, 1)

    title = "  <h1>PR assigment overview</h1>"
    welcome = "<p>This is a hidden page, meant for maintainers: it allows seeing which PRs are assigned to whom. In the future, this page will also contains suggestions for appropriate reviewers, or provide the means to contact them.</p>"

    header = "<h2>PR assignment statistics</h2>"
    intro = f"The following table contains statistics about all PRs whose number is greater than {threshold}.<br>"
    num_ass_open = len(set(assigned_open_prs))
    stat = (f"Overall, <b>{num_ass_open}</b> of these <b>{number_open_prs}</b> open PRs (<b>{num_ass_open/number_open_prs:.1%}</b>) have at least one assignee. "
      f"Among these, <strong>{multiple_assignees}</strong> have more than one assignee.")
    all_recent = f'<a title="number of all assigned PRs whose PR number is greater than {threshold}">Number of all recent PRs</a>'
    thead = _write_table_header(["User", "Open assigned PR(s)", "Number of them", all_recent], "    ")
    tbody = ""
    for (name, (prs, n_open, n_all)) in numbers.items():
        formatted_prs = [pr_link(int(pr), f"https://github.com/leanprover-community/mathlib4/pull/{pr}") for pr in prs]
        tbody += _write_table_row([user_link(name), ', '.join(formatted_prs), n_open, n_all], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    stats = f"{header}\n{intro}\n{stat}\n{table}"

    header = "<h2>Mathlib reviewers with areas of interest</h2>"
    intro = "The following lists all mathlib reviewers with their (self-declared) topics of interest. Beware: need to update the json file with reviewer interests!"
    # Future: download the raw file from this link, instead of reading a local copy!
    # (This requires fixing the upstream version first: locally, it is easy to just correct the bugs.)
    _file_url = "https://raw.githubusercontent.com/leanprover-community/mathlib4/edbf78c660496a4236d23c8c3b74133a59fdf49b/docs/reviewer-topics.json"
    with open("reviewer-topics.json", "r") as fi:
        reviewer_topics = json.load(fi)
    thead = _write_table_header(["Github username", "Zulip handle", "Topic areas", "Comments", "Currently assigned PRs"], "    ")
    # XXX: clarify the threshold again!
    tbody = ""
    for entry in reviewer_topics:
        github = entry["github_handle"]
        topic_areas = entry["top_level"]
        comment = entry["free_form"]
        tbody += _write_table_row([github, entry["zulip_handle"], topic_areas, comment, numbers.get(github) or 0], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    reviewers = f"{header}\n{intro}\n{table}"

    write_webpage(f"{title}\n{welcome}\n{stats}\n{reviewers}", "assign-reviewer.html")

main()