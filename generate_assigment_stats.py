#!/usr/bin/env python3

import json
from os import path
import sys
from typing import List, NamedTuple, Tuple

from classify_pr_state import CIStatus
from dashboard import AggregatePRInfo, BasicPRInformation, Dashboard, ExtraColumnSettings, _write_labels, _write_table_header, _write_table_row, determine_pr_dashboards, infer_pr_url, parse_aggregate_file, pr_link, title_link, user_link, write_dashboard, write_webpage


# Assumes the aggregate data is correct: no cross-filling in of placeholder data.
def compute_pr_list_from_aggregate_data_only(aggregate_data: dict[int, AggregatePRInfo]):
    nondraft_PRs: List[BasicPRInformation] = []
    for (pr, data) in aggregate_data.items():
        if data.state == 'open' and not data.is_draft:
            nondraft_PRs.append(BasicPRInformation(
                pr, data.author, data.title, infer_pr_url(pr),
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
    top_level: List[str]
    comment: str


def suggest_reviewers(reviewers: List[ReviewerInfo], number: int, info: AggregatePRInfo) -> str:
    # Look at all topic labels of this PR, and find all suitable reviewers.
    topic_labels = [lab.name for lab in info.labels if lab.name.startswith("t-") or lab.name in ['CI', 'IMO']]
    matching_reviewers: List[Tuple[ReviewerInfo, List[str]]] = []
    if topic_labels:
        for rev in reviewers:
            reviewer_lab = rev.top_level
            if "t-metaprogramming" in reviewer_lab:
                reviewer_lab.remove("t-metaprogramming"); reviewer_lab.append("t-meta")
            match = [lab for lab in topic_labels if lab in reviewer_lab]
            matching_reviewers.append((rev, match))
    else:
        print(f"PR {number} is has no topic labels: reviewer suggestions not implemented yet", file=sys.stderr)
        return "no topic labels: suggestions not implemented yet"

    # Future: decide how to customise and filter the output, lots of possibilities!
    # - no and one reviewer look sensible already
    #   (should one show their full interests also? would that be interesting?)
    # - don't suggest more than five reviewers --- but make clear there was a selection
    #   perhaps: have two columns "all matching reviewers" and "suggested one(s)" with up to three?
    # - would showing the full interests (not just the top-level areas) be helpful?
    if not matching_reviewers:
        print(f"found no reviewers with matching interest for PR {number}", file=sys.stderr)
        return "found no reviewers with matching interest"
    elif len(matching_reviewers) == 1:
        rev = matching_reviewers[0]
        return f"{user_link(rev.github)}"
    else:
        max_score = max([len(n) for (_, n) in matching_reviewers])
        if max_score > 1:
            # If there are several areas, prefer reviewers which match the highest number of them.
            max_reviewers = [(rev, areas) for (rev, areas) in matching_reviewers if len(areas) == max_score]
            # FIXME: refine which information is actually useful here.
            # Or also show information if a single (and the PR's only) area matches?
            formatted = ", ".join([
                user_link(rev.github, "competent in {}".format(", ".join(areas)))
                for (rev, areas) in max_reviewers
            ])
        else:
            comment = lambda comment: f"; comments: {comment}" if comment else ""
            formatted = ", ".join([
                user_link(rev.github, f"areas of competence: {', '.join(rev.top_level)}{comment(rev.comment)}")
                for (rev, areas) in matching_reviewers if len(areas) > 0
            ])
        return formatted

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
    welcome = "<p>This is a hidden page, meant for maintainers: it displays information on which PRs are assigned and suggests appropriate reviewers for unassigned PRs. In the future, it could provide the means to contact them. To prevent spam, for now this page is a bit hidden: it has to be generated locally from a script.</p>"

    header = '<h2 id="#assignment-stats"><a href="#assignment-stats">PR assignment statistics</a></h2>'
    intro = f"The following table contains statistics about all PRs whose number is greater than {threshold}.<br>"
    num_ass_open = len(set(assigned_open_prs))
    stat = (f"Overall, <b>{num_ass_open}</b> of these <b>{number_open_prs}</b> open PRs (<b>{num_ass_open/number_open_prs:.1%}</b>) have at least one assignee. "
      f"Among these, <strong>{multiple_assignees}</strong> have more than one assignee.")
    all_recent = f'<a title="number of all assigned PRs whose PR number is greater than {threshold}">Number of all recent PRs</a>'
    # NB. Add an empty column to please the formatting script.
    thead = _write_table_header(["User", "Open assigned PR(s)", "Number of them", all_recent, ""], "    ")
    tbody = ""
    for (name, (prs, n_open, n_all)) in numbers.items():
        formatted_prs = [pr_link(int(pr), infer_pr_url(pr)) for pr in prs]
        tbody += _write_table_row([user_link(name), ', '.join(formatted_prs), n_open, n_all, ""], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    stats = f"{header}\n{intro}\n{stat}\n{table}"

    header = '<h2 id="#reviewers"><a href="#reviewers">Mathlib reviewers with areas of interest</a></h2>'
    intro = "The following lists all mathlib reviewers with their (self-declared) topics of interest. (Beware: still need a solution for keep this file in sync with the 'master' data.)"
    # Future: download the raw file from this link, instead of reading a local copy!
    # (This requires fixing the upstream version first: locally, it is easy to just correct the bugs.)
    # And perhaps the file could be part of the mathlib repo, or the webpage?
    _file_url = "https://raw.githubusercontent.com/leanprover-community/mathlib4/edbf78c660496a4236d23c8c3b74133a59fdf49b/docs/reviewer-topics.json"
    with open("reviewer-topics.json", "r") as fi:
        reviewer_topics = json.load(fi)
    parsed_reviewers: List[ReviewerInfo] = [
        ReviewerInfo(entry["github_handle"], entry["zulip_handle"], entry["top_level"], entry["free_form"]) for entry in reviewer_topics
    ]
    curr = f"<a title='only considering PRs with number > {threshold}'>Currently assigned PRs</a>"
    # NB. Add an empty column to please the formatting script.
    thead = _write_table_header(["Github username", "Zulip handle", "Topic areas", "Comments", curr, ""], "    ")
    tbody = ""
    for rev in parsed_reviewers:
        if rev.github in numbers:
            num = numbers[rev.github]
            numbers = f'<a title="{num[2]} PRs > {threshold} ever assigned">{num[0] or "none"}</a>'
        else:
            numbers = "none ever"
        tbody += _write_table_row([rev.github, rev.zulip, rev.top_level, rev.comment, numbers, ""], "    ")
    table = f"  <table>\n{thead}{tbody}  </table>"
    reviewers = f"{header}\n{intro}\n{table}"

    header = '<h2 id="#propose-reviewers"><a href="#propose-reviewers">Finding reviewers for unassigned PRs</h2>'
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

    write_webpage(f"{title}\n{welcome}\n{stats}\n{reviewers}\n{propose}", "assign-reviewer.html")

main()