#!/usr/bin/env python3

"""
Generate a webpage
- displaying statistics about how many reviewers have how many PR assigned to them,
- suggesting potential reviewers for unassigned PRs, based on their self-indicated areas of competence/interest

"""

import json
import sys
from os import path
from typing import List, NamedTuple, Tuple

from classify_pr_state import CIStatus
from dashboard import (
    AggregatePRInfo,
    BasicPRInformation,
    Dashboard,
    ExtraColumnSettings,
    _write_table_header,
    _write_table_row,
    determine_pr_dashboards,
    infer_pr_url,
    parse_aggregate_file,
    pr_link,
    user_link,
    write_dashboard,
    write_webpage,
)


# Assumes the aggregate data is correct: no cross-filling in of placeholder data.
def compute_pr_list_from_aggregate_data_only(aggregate_data: dict[int, AggregatePRInfo]) -> dict[Dashboard, List[BasicPRInformation]]:
    nondraft_PRs: List[BasicPRInformation] = []
    for (number, data) in aggregate_data.items():
        if data.state == 'open' and not data.is_draft:
            nondraft_PRs.append(BasicPRInformation(
                number, data.author, data.title, infer_pr_url(number),
                data.labels, data.last_updated
            ))
    CI_status: dict[int, CIStatus] = dict()
    for pr in nondraft_PRs:
        if pr.number in aggregate_data:
            CI_status[pr.number] = aggregate_data[pr.number].CI_status
        else:
            CI_status[pr.number] = CIStatus.Missing
    base_branch: dict[int, str] = dict()
    for pr in nondraft_PRs:
        base_branch[pr.number] = aggregate_data[pr.number].base_branch
    prs_from_fork = [pr for pr in nondraft_PRs if aggregate_data[pr.number].head_repo != "leanprover-community"]
    return determine_pr_dashboards(nondraft_PRs, base_branch, prs_from_fork, CI_status, aggregate_data, True)


class ReviewerInfo(NamedTuple):
    github: str
    zulip: str
    # List of top-level areas a reviewer is interested in.
    # Most (but not all) of these are t-something labels in mathlib.
    top_level: List[str]
    comment: str


def read_reviewer_info() -> List[ReviewerInfo]:
    # Future: download the raw file from this link, instead of reading a local copy!
    # (This requires fixing the upstream version first: locally, it is easy to just correct the bugs.)
    # And the file should live on a more stable branch (master?), or the webpage?
    _file_url = "https://raw.githubusercontent.com/leanprover-community/mathlib4/refs/heads/reviewer-topics/docs/reviewer-topics.json"
    with open("reviewer-topics.json", "r") as fi:
        reviewer_topics = json.load(fi)
    return [
        ReviewerInfo(entry["github_handle"], entry["zulip_handle"], entry["top_level"], entry["free_form"])
        for entry in reviewer_topics
    ]

# Return a tuple (full code, reviewers): the former is used as the webpage table entry,
# the latter are all potential reviewers suggested (by their github handle).
def suggest_reviewers(reviewers: List[ReviewerInfo], number: int, info: AggregatePRInfo) -> Tuple[str, List[str]]:
    # Look at all topic labels of this PR, and find all suitable reviewers.
    topic_labels = [lab.name for lab in info.labels if lab.name.startswith("t-") or lab.name in ["CI", "IMO"]]
    matching_reviewers: List[Tuple[ReviewerInfo, List[str]]] = []
    if topic_labels:
        for rev in reviewers:
            reviewer_lab = rev.top_level
            if "t-metaprogramming" in reviewer_lab:
                reviewer_lab.remove("t-metaprogramming")
                reviewer_lab.append("t-meta")
            match = [lab for lab in topic_labels if lab in reviewer_lab]
            matching_reviewers.append((rev, match))
    else:
        print(f"PR {number} is has no topic labels: reviewer suggestions not implemented yet", file=sys.stderr)
        return ("no topic labels: suggestions not implemented yet", [])

    # Future: decide how to customise and filter the output, lots of possibilities!
    # - no and one reviewer look sensible already
    #   (should one show their full interests also? would that be interesting?)
    # - don't suggest more than five reviewers --- but make clear there was a selection
    #   perhaps: have two columns "all matching reviewers" and "suggested one(s)" with up to three?
    # - would showing the full interests (not just the top-level areas) be helpful?
    if not matching_reviewers:
        print(f"found no reviewers with matching interest for PR {number}", file=sys.stderr)
        return ("found no reviewers with matching interest", [])
    elif len(matching_reviewers) == 1:
        handle = matching_reviewers[0][0].github
        return (f"{user_link(handle)}", [handle])
    else:
        max_score = max([len(areas) for (_, areas) in matching_reviewers])
        if max_score > 1:
            # If there are several areas, prefer reviewers which match the highest number of them.
            max_reviewers = [(rev, areas) for (rev, areas) in matching_reviewers if len(areas) == max_score]
            # FIXME: refine which information is actually useful here.
            # Or also show information if a single (and the PR's only) area matches?
            formatted = ", ".join([
                user_link(rev.github, "competent in {}".format(", ".join(areas)))
                for (rev, areas) in max_reviewers
            ])
            suggested_reviewers = [rev.github for (rev, _areas) in max_reviewers]
        else:
            def comment(comm: str):
                return f"; comments: {comment}" if comm else ""
            formatted = ", ".join([
                user_link(rev.github, f"areas of competence: {', '.join(rev.top_level)}{comment(rev.comment)}")
                for (rev, areas) in matching_reviewers if len(areas) > 0
            ])
            suggested_reviewers = [rev.github for (rev, areas) in matching_reviewers if len(areas) > 0]
        return (formatted, suggested_reviewers)


class AssignmentStatistics(NamedTuple):
    # We ignore all PRs whose number lies below this threshold: so far, the aggregate file
    # only contains information about a third of all PRs; we prefer to not issue statistics
    # based on such incomplete data (which is gradually becoming more complete).
    # This is part of the data to avoid "very silently" confusing different statistics.
    threshold: int
    # The number of all open PRs whose number is at >= |threshold|.
    num_open_above: int
    # All PRs >= threshold which are open and assigned to somebody.
    # This list is deduplicated.
    assigned_open_above: List[int]
    # The number of PRs (>= |threshold|) with multiple assignees.
    number_multiple_assignees: int
    # Collating all assigned PRs above the threshold: map each user to a tuple
    # (numbers, n_open, n_all), where
    # - numbers is a list of open PRs that are assigned
    # - n_open is the *number* of these assigned open PRs,
    # - n_all is the number of all PRs (above threshold) ever assigned to this user.
    # Note that a PR assigned to several users is counted multiple times, once per assignee.
    assignments: dict[str, Tuple[List[int], int, int]]


def collect_assignment_statistics(parsed: dict) -> AssignmentStatistics:
    with open(path.join("processed_data", "assignment_data.json"), "r") as fi:
        assignment_data = json.load(fi)
    threshold = assignment_data["threshold"]
    num_open_above_threshold = assignment_data["number_open_above_threshold"]
    assignments = assignment_data["all_assignments"]
    numbers: dict[str, Tuple[List[int], int, int]] = {}
    assigned_open_prs = []
    for (reviewer, data) in assignments.items():
        above_threshold = [entry for entry in data if entry["number"] >= threshold]
        open_above_threshold = sorted([entry["number"] for entry in above_threshold if entry["state"] == "open"])
        numbers[reviewer] = (open_above_threshold, len(open_above_threshold), len(above_threshold))
        assigned_open_prs.extend(open_above_threshold)
    num_multiple_assignees = len(assigned_open_prs) - len(set(assigned_open_prs))
    assert assignment_data["number_open_assigned_above_threshold"] == len(list(set(assigned_open_prs)))
    return AssignmentStatistics(threshold, num_open_above_threshold, sorted(list(set(assigned_open_prs))), num_multiple_assignees, numbers)


def main() -> None:
    with open(path.join("processed_data", "all_pr_data.json"), "r") as fi:
        parsed = parse_aggregate_file(json.load(fi))
    stats = collect_assignment_statistics(parsed)

    title = "  <h1>PR assigment overview</h1>"
    welcome = "<p>This is a hidden page, meant for maintainers: it displays information on which PRs are assigned and suggests appropriate reviewers for unassigned PRs. In the future, it could provide the means to contact them. To prevent spam, for now this page is a bit hidden: it has to be generated locally from a script.</p>"

    header = '<h2 id="assignment-stats"><a href="#assignment-stats">PR assignment statistics</a></h2>'
    intro = f"The following table contains statistics about all open PRs whose number is greater than {stats.threshold}.<br>"
    stat = (
        f"Overall, <b>{len(stats.assigned_open_above)}</b> of these <b>{stats.num_open_above}</b> open PRs (<b>{len(stats.assigned_open_above)/stats.num_open_above:.1%}</b>) have at least one assignee. "
        f"Among these, <strong>{stats.number_multiple_assignees}</strong> have more than one assignee."
    )
    all_recent = f'<a title="number of all assigned PRs whose PR number is greater than {stats.threshold}">Number of all recent PRs</a>'
    # NB. Add an empty column to please the formatting script.
    thead = _write_table_header(["User", "Open assigned PR(s)", "Number of them", all_recent, ""], "    ")
    tbody = ""
    for name, (prs, n_open, n_all) in stats.assignments.items():
        formatted_prs = [pr_link(int(pr), infer_pr_url(pr)) for pr in prs]
        tbody += _write_table_row([user_link(name), ", ".join(formatted_prs), str(n_open), str(n_all), ""], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    stats_section = f"{header}\n{intro}\n{stat}\n{table}"

    header = '<h2 id="reviewers"><a href="#reviewers">Mathlib reviewers with areas of interest</a></h2>'
    intro = "The following lists all mathlib reviewers with their (self-declared) topics of interest. (Beware: still need a solution for keep this file in sync with the 'master' data.)"

    parsed_reviewers = read_reviewer_info()
    curr = f"<a title='only considering PRs with number > {stats.threshold}'>Currently assigned PRs</a>"
    # NB. Add an empty column to please the formatting script.
    thead = _write_table_header(["Github username", "Zulip handle", "Topic areas", "Comments", curr, ""], "    ")
    tbody = ""
    for rev in parsed_reviewers:
        if rev.github in stats.assignments:
            (pr_numbers, _n_open, n_all) = stats.assignments[rev.github]
            desc = f'<a title="{n_all} PRs > {stats.threshold} ever assigned">{", ".join([str(n) for n in pr_numbers]) or "none"}</a>'
        else:
            desc = "none ever"
        tbody += _write_table_row([rev.github, rev.zulip, ", ".join(rev.top_level), rev.comment, desc, ""], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    reviewers = f"{header}\n{intro}\n{table}"

    header = '<h2 id="propose-reviewers"><a href="#propose-reviewers">Finding reviewers for unassigned PRs</a></h2>'
    pr_lists = compute_pr_list_from_aggregate_data_only(parsed)
    suggestions = {
        pr.number: suggest_reviewers(parsed_reviewers, pr.number, parsed[pr.number])
        for pr in pr_lists[Dashboard.QueueStaleUnassigned]
    }
    # Future: have another column with a button to send a zulip DM to a
    # potential (e.g. selecting from the suggested ones).
    settings = ExtraColumnSettings(show_assignee=False, show_approvals=True, potential_reviewers=True, hide_update=True)
    table = write_dashboard(pr_lists, Dashboard.QueueStaleUnassigned, parsed, settings, False, suggestions)
    propose = f"{header}\n{table}\n"
    # NB. This line becomes actual javascript code, so uses JS' string interpolation syntax.
    msg = "Dear ${name}, I'm triaging unassigned PRs. #${number} matches your interests; would you like to review it? Thanks!"
    extra = "  function contactMessage(name, number) {\n    alert(`msg`);\n  }".replace("msg", msg)

    write_webpage(f"{title}\n{welcome}\n{stats_section}\n{reviewers}\n{propose}", "assign-reviewer.html", extra_script=extra)


main()
