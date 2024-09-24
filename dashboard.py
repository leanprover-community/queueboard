#!/usr/bin/env python3

# This script accepts json files as command line arguments and displays the data in an HTML dashboard

import json
import sys
from datetime import datetime, timezone
from enum import Enum, auto, unique
from typing import List, NamedTuple, Tuple

from dateutil.relativedelta import relativedelta

from classify_pr_state import (CIStatus, PRState, PRStatus,
                               determine_PR_status, label_categorisation_rules)


@unique
class PRList(Enum):
    '''The different kind of PR lists this dashboard creates'''
    # Note: the tables on the generated page are listed in the order of these variants.
    Queue = 0
    QueueNewContributor = auto()
    QueueEasy = auto()
    StaleReadyToMerge = auto()
    StaleDelegated = auto()
    StaleMaintainerMerge = auto()
    # This PR is blocked on a zulip discussion or similar.
    NeedsDecision = auto()
    # PRs passes, but just has a merge conflict: same labels as for review, except we do require a merge conflict
    NeedsMerge = auto()
    StaleNewContributor = auto()
    # Labelled please-adopt or help-wanted
    NeedsHelp = auto()
    # Non-draft PRs into some branch other than mathlib's master branch
    OtherBase = auto()
    # "Ready" PRs without the CI or a t-something label.
    Unlabelled = auto()
    # "Ready" PRs whose title does not start with an abbreviation like 'feat' or 'style'
    BadTitle = auto()
    # This PR carries inconsistent labels, such as "WIP" and "ready-to-merge".
    ContradictoryLabels = auto()


# All input files this script expects. Needs to be kept in sync with dashboard.sh,
# but this script will complain if something unexpected happens.
EXPECTED_INPUT_FILES = {
    "queue.json" : PRList.Queue,
    "ready-to-merge.json" : PRList.StaleReadyToMerge,
    "automerge.json" : PRList.StaleReadyToMerge,
    "needs-merge.json" : PRList.NeedsMerge,
    "maintainer-merge.json" : PRList.StaleMaintainerMerge,
    "needs-decision.json" : PRList.NeedsDecision,
    "delegated.json" : PRList.StaleDelegated,
    "other-base-branch.json" : PRList.OtherBase,
    "new-contributor.json" : PRList.StaleNewContributor,
    "please-adopt.json" : PRList.NeedsHelp,
    "help-wanted.json" : PRList.NeedsHelp,
}

def short_description(kind : PRList) -> str:
    '''Describe what the table 'kind' contains, for use in a "there are no such PRs" message.'''
    return {
        PRList.Queue : "PRs on the review queue",
        PRList.QueueNewContributor : "PRs by new mathlib contributors on the review queue",
        PRList.QueueEasy : "PRs on the review queue which are labelled 'easy'",
        PRList.StaleMaintainerMerge : "stale PRs labelled maintainer merge",
        PRList.StaleDelegated : "stale delegated PRs",
        PRList.StaleReadyToMerge : "stale PRs labelled auto-merge-after-CI or ready-to-merge",
        PRList.NeedsDecision : "PRs blocked on a zulip discussion or similar",
        PRList.NeedsMerge : "PRs which just have a merge conflict",
        PRList.StaleNewContributor : "stale PRs by new contributors",
        PRList.NeedsHelp : "PRs which are looking for a help",
        PRList.OtherBase : "ready PRs into a non-master branch",
        PRList.Unlabelled : "ready PRs without a 'CI' or 't-something' label",
        PRList.BadTitle : "ready PRs whose title does not start with an abbreviation like 'feat', 'style' or 'perf'",
        PRList.ContradictoryLabels : "PRs with contradictory labels",
    }[kind]

def long_description(kind : PRList) -> str:
    '''Explain what each PR list contains: full description, for the purposes of a sub-title
    to the full PR table. This description should not be capitalised.'''
    notupdated = "which have not been updated in the past"
    return {
        PRList.Queue : "all PRs which are ready for review: CI passes, no merge conflict and not blocked on other PRs",
        PRList.QueueNewContributor : "all PRs by new contributors which are ready for review",
        PRList.QueueEasy : "all PRs labelled 'easy' which are ready for review",
        PRList.NeedsMerge : "all PRs which have a merge conflict, but otherwise fit the review queue",
        PRList.StaleDelegated : f"all PRs labelled 'delegated' {notupdated} 24 hours",
        PRList.StaleReadyToMerge : f"all PRs labelled 'auto-merge-after-CI' or 'ready-to-merge' {notupdated} 24 hours",
        PRList.NeedsDecision : "all PRs labelled 'awaiting-zulip': these are blocked on a zulip discussion or similar",
        PRList.StaleMaintainerMerge : f"all PRs labelled 'maintainer-merge' but not 'ready-to-merge' {notupdated} 24 hours",
        PRList.NeedsHelp : "all PRs which are labelled 'please-adopt' or 'help-wanted'",
        PRList.OtherBase : "all non-draft PRs into some branch other than mathlib's master branch",
        PRList.StaleNewContributor : f"all PR labelled 'new-contributor' {notupdated} 7 days",
        PRList.Unlabelled : "all PRs without draft status or 'WIP' label without a 'CI' or 't-something' label",
        PRList.BadTitle : "all PRs without draft status or 'WIP' label whose title does not start with an abbreviation like 'feat', 'style' or 'perf'",
        PRList.ContradictoryLabels : "PRs whose labels are contradictory, such as 'WIP' and 'ready-to-merge'",
    }[kind]

def getIdTitle(kind : PRList) -> Tuple[str, str]:
    '''Return a tuple (id, title) of the HTML anchor ID and a section name for the table
    describing this PR kind.'''
    return {
        PRList.Queue : ("queue", "Review queue"),
        PRList.QueueNewContributor : ("queue-new-contributors", "New contributors' PRs on the queue"),
        PRList.QueueEasy : ("queue-easy", "PRs on the review queue labelled 'easy'"),
        PRList.StaleDelegated : ("stale-delegated", "Stale delegated PRs"),
        PRList.StaleNewContributor : ("stale-new-contributor", "Stale new contributor PRs"),
        PRList.StaleMaintainerMerge : ("stale-maintainer-merge", "Stale maintainer-merge'd PRs"),
        PRList.StaleReadyToMerge : ("stale-ready-to-merge", "Stale ready-to-merge'd PRs"),
        PRList.NeedsDecision : ("needs-decision", "PRs blocked on a zulip discussion"),
        PRList.NeedsMerge : ("needs-merge", "PRs with just a merge conflict"),
        PRList.NeedsHelp : ("needs-owner", "PRs looking for help"),
        PRList.OtherBase : ("other-base", "PRs not into the master branch"),
        PRList.Unlabelled : ("unlabelled", "PRs without an area label"),
        PRList.BadTitle : ("bad-title", "PRs with non-conforming titles"),
        PRList.ContradictoryLabels : ("contradictory-labels", "PRs with contradictory labels"),
    }[kind]

def main() -> None:
    # Check if the user has provided the correct number of arguments
    if len(sys.argv) < 4:
        print("Usage: python3 dashboard.py <pr-info.json> <all-nondraft-prs.json> <all-draft-PRs.json> <json_file1> <json_file2> ...")
        sys.exit(1)

    print_html5_header()

    # Print a quick table of contents.
    links = []
    for kind in PRList._member_map_.values():
        (id, _title) = getIdTitle(kind)
        links.append(f"<a href=\"#{id}\" title=\"{short_description(kind)}\" target=\"_self\">{id}</a>")
    print(f"<br><p>\n<b>Quick links:</b> <a href=\"#statistics\" target=\"_self\">PR statistics</a> | {str.join(' | ', links)}</p>")

    # Iterate over the json files provided by the user
    dataFilesWithKind = []
    for i in range(4, len(sys.argv)):
        filename = sys.argv[i]
        if filename not in EXPECTED_INPUT_FILES:
            print(f"bad argument: file {filename} is not recognised; did you mean one of these?\n{', '.join(EXPECTED_INPUT_FILES.keys())}")
            sys.exit(1)
        with open(filename) as f:
            data = json.load(f)
            dataFilesWithKind.append((data, EXPECTED_INPUT_FILES[filename]))

    with open(sys.argv[2]) as ready_file, open(sys.argv[3]) as draft_file:
        all_nondraft_prs = json.load(ready_file)
        all_draft_prs = json.load(draft_file)
        print(gather_pr_statistics(dataFilesWithKind, all_nondraft_prs, all_draft_prs))

        queue_data = [d for (d, k) in dataFilesWithKind if k == PRList.Queue]
        print_queue_boards(queue_data)
        # Process all data files for the same PR list together.
        for kind in PRList._member_map_.values():
            if kind in [PRList.Queue, PRList.QueueNewContributor, PRList.QueueEasy]:
                continue # These dashboards were just printed above.
            # For these kinds, we create a dashboard later (by filtering the list of all ready PRs instead).
            if kind in [PRList.Unlabelled, PRList.BadTitle, PRList.ContradictoryLabels]:
                continue
            datae = [d for (d, k) in dataFilesWithKind if k == kind]
            print_dashboard(datae, kind)

        print_dashboard_bad_labels_title(all_nondraft_prs)

    print_html5_footer()


def gather_pr_statistics(dataFilesWithKind: List[Tuple[dict, PRList]], all_ready_prs: dict, all_draft_prs: dict) -> str:
    def determine_status(info: BasicPRInformation, is_draft: bool) -> PRStatus:
        # Ignore all "other" labels, which are not relevant for this anyway.
        labels = [label_categorisation_rules[l.name] for l in info.labels if l.name in label_categorisation_rules]
        state = PRState(labels, CIStatus.Pass, is_draft)
        return determine_PR_status(datetime.now(), state)

    ready_prs : List[BasicPRInformation] = _extract_prs([all_ready_prs])
    # Collect the status of every ready PR.
    # FIXME: we assume every PR is passing CI, which is too optimistic
    # We would like to choose the `BasicPRInformation` as the key; as these are not hashable,
    # we index by the PR number instead.
    ready_pr_status : dict[int, PRStatus] = {
       info.number: determine_status(info, False) for info in ready_prs
    }
    draft_prs = _extract_prs([all_draft_prs])
    queue_prs = _extract_prs([d for (d, k) in dataFilesWithKind if k == PRList.Queue])
    justmerge_prs = _extract_prs([d for (d, k) in dataFilesWithKind if k == PRList.NeedsMerge])

    # Collect the number of PRs in each possible status.
    # NB. The order of these statusses is meaningful; the statistics are shown in the order of these items.
    statusses = [
        PRStatus.AwaitingReview, PRStatus.Blocked, PRStatus.AwaitingAuthor, PRStatus.MergeConflict,
        PRStatus.HelpWanted,PRStatus.NotReady,
        PRStatus.AwaitingDecision,
        PRStatus.Contradictory,
        PRStatus.Delegated, PRStatus.AwaitingBors,
    ]
    number_prs : dict[PRStatus, int] = {
        status : len([number for number in ready_pr_status if ready_pr_status[number] == status]) for status in statusses
    }
    number_prs[PRStatus.NotReady] += len(draft_prs)
    # Check that we did not miss any variant above
    for status in PRStatus._member_map_.values():
        assert status == PRStatus.Closed or status in number_prs.keys()

    # For some kinds, we have this data already: the review queue and the "not merged" kinds come to mind.
    # Let us compare with the classification logic.
    queue_prs_numbers = [pr for pr in ready_pr_status if ready_pr_status[pr] == PRStatus.AwaitingReview]
    if queue_prs_numbers != [i.number for i in queue_prs]:
        right = [i.number for i in queue_prs]
        print(f"warning: the review queue and the classification differ: found {len(right)} PRs {right} on the former, but the {len(queue_prs_numbers)} PRs {queue_prs_numbers} on the latter!", file=sys.stderr)
    # TODO: also cross-check the data for merge conflicts

    number_all = len(ready_prs) + len(draft_prs)
    def link_to(kind: PRList, name="these ones") -> str:
        return f"<a href=\"#{getIdTitle(kind)[0]}\" target=\"_self\">{name}</a>"
    def number_percent(n: int , total: int, color: str = "") -> str:
        if color:
            return f"{n} (<span style=\"color: {color};\">{n/total:.1%}</span>)"
        else:
            return f"{n} (<span>{n/total:.1%}</span>)"
    instatus = {
        PRStatus.AwaitingReview: f"are awaiting review ({link_to(PRList.Queue)})",
        PRStatus.HelpWanted: f"are labelled help-wanted or please-adopt ({link_to(PRList.NeedsHelp, 'roughly these')})",
        PRStatus.AwaitingAuthor: "are awaiting the PR author's action",
        PRStatus.AwaitingDecision: f"are awaiting the outcome of a zulip discussion ({link_to(PRList.NeedsDecision)})",
        PRStatus.Blocked: "are blocked on another PR",
        PRStatus.Delegated: f"are delegated (stale ones are {link_to(PRList.StaleDelegated, 'here')})",
        PRStatus.AwaitingBors: f"have been sent to bors (stale ones are {link_to(PRList.StaleReadyToMerge, 'here')})",
        PRStatus.MergeConflict: f"have a merge conflict: among these, <b>{number_percent(len(justmerge_prs), number_all)}</b> would be ready for review otherwise: {link_to(PRList.NeedsMerge, 'these')}",
        PRStatus.Contradictory: f"have contradictory labels ({link_to(PRList.ContradictoryLabels)})",
        PRStatus.NotReady: "are marked as draft or work in progress",
    }
    assert set(instatus.keys()) == set(statusses)
    color = {
        PRStatus.AwaitingReview: "#33b4ec",
        PRStatus.HelpWanted: "#cc317c",
        PRStatus.AwaitingAuthor: "#f6ae9a",
        PRStatus.AwaitingDecision: "#086ad4",
        PRStatus.Blocked: "#8A6A1C",
        PRStatus.Delegated: "#689dea",
        PRStatus.AwaitingBors: "#098306",
        PRStatus.MergeConflict: "#f17075",
        PRStatus.Contradictory: "black",
        PRStatus.NotReady: "#e899cd",
    }
    assert set(color.keys()) == set(statusses)
    details = '\n'.join([f"  <li><b>{number_percent(number_prs[s], number_all, color[s])}</b> {instatus[s]}</li>" for s in statusses])
    # Generate a simple pie chart showing the distribution of PR statusses.
    # Doing so requires knowing the cumulative sums, of all statusses so far.
    numbers = [number_prs[s] for s in statusses]
    cumulative = [sum(numbers[:i+1]) for i in range(len(numbers))]
    piechart = ', '.join([f'{color[s]} 0 {cumulative[i] * 360 // number_all}deg' for (i, s) in enumerate(statusses)])
    piechart_style=f"width: 200px;height: 200px;border-radius: 50%;border: 1px solid black;background-image: conic-gradient( {piechart} );"

    return f"\n<h2 id=\"statistics\"><a href=\"#statistics\">Overall statistics</a></h2>\nFound <b>{number_all}</b> open PRs overall. Disregarding their CI state, of these PRs\n<ul>\n{details}\n</ul><div class=\"piechart\" style=\"{piechart_style}\"></div>\n"


def print_html5_header() -> None:
    print("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Mathlib review and triage dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.5.1/jquery.min.js"
			integrity="sha512-bLT0Qm9VnAYZDflyKcBaQ2gg0hSYNQrJ8RilYldYQ1FxQYoCLtUjuuRuZo+fjqhx/qtq/1itJ0C2ejDxltZVFg=="
			crossorigin="anonymous"></script>
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.10.22/css/jquery.dataTables.css">
    <script type="text/javascript" charset="utf8" src="https://cdn.datatables.net/1.10.22/js/jquery.dataTables.js"></script>
    <link rel='stylesheet' href='style.css'>
    <base target="_blank">
    </head>
    <body>
    <h1>Mathlib review and triage dashboard</h1>""")
    # FUTURE: can this time be displayed in the local time zone of the user viewing this page?
    updated = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    print(f"""<small>This dashboard was last updated on: {updated}<br>
        Feedback on this dashboard is welcome, for instance <a href="https://github.com/jcommelin/queueboard">directly on the github repository</a>.</small>""")

def print_html5_footer() -> None:
    print("""
    <script>
    $(document).ready( function () {
        $('table').DataTable({
            pageLength: 10,
			"searching": true,
        });
    });
    </script>
    </body>
    </html>
    """)

# An HTML link to a mathlib PR from the PR number
def pr_link(number: int, url: str) -> str:
    return "<a href='{}'>#{}</a>".format(url, number)

# An HTML link to a GitHub user profile
def user_link(author: dict) -> str:
    login = author["login"]
    url   = author["url"]
    return "<a href='{}'>{}</a>".format(url, login)

# An HTML link to a mathlib PR from the PR title
def title_link(title: str, url: str) -> str:
    return "<a href='{}'>{}</a>".format(url, title)


# The information we need about each PR label: its name, background colour and URL
class Label(NamedTuple):
    name : str
    '''This label's background colour, as a six-digit hexadecimal code'''
    color : str
    url : str


# An HTML link to a Github label in the mathlib repo
def label_link(label:Label) -> str:
    # Function to check if the colour of the label is light or dark
    # adapted from https://codepen.io/WebSeed/pen/pvgqEq
    # r, g and b are integers between 0 and 255.
    def isLight(r : int, g: int, b: int) -> bool:
        # Counting the perceptive luminance
        # human eye favors green color...
        a = 1 - (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return (a < 0.5)

    bgcolor = label.color
    fgcolor = "000000" if isLight(int(bgcolor[:2], 16), int(bgcolor[2:4], 16), int(bgcolor[4:], 16)) else "FFFFFF"
    return f"<a href='{label.url}'><span class='label' style='color: #{fgcolor}; background: #{bgcolor}'>{label.name}</span></a>"


def format_delta(delta: relativedelta) -> str:
    if delta.years > 0:
        return f"{delta.years} years"
    elif delta.months > 0:
        return f"{delta.months} months"
    elif delta.days > 0:
        return f"{delta.days} days"
    elif delta.hours > 0:
        return f"{delta.hours} hours"
    elif delta.minutes > 0:
        return f"{delta.minutes} minutes"
    else:
        return f"{delta.seconds} seconds"


# Function to format the time of the last update
# Input is in the format: "2020-11-02T14:23:56Z"
# Output is in the format: "2020-11-02 14:23 (2 days ago)"
def time_info(updatedAt: str) -> str:
    updated = datetime.strptime(updatedAt, "%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now()
    # Calculate the difference in time
    delta = relativedelta(now, updated)
    # Format the output
    s = updated.strftime("%Y-%m-%d %H:%M")
    return f"{s} ({format_delta(delta)} ago)"


# Basic information about a PR: does not contain the diff size, which is contained in pr_info.json instead.
class BasicPRInformation(NamedTuple):
    number : int # PR number, non-negative
    author : dict
    title : str
    url : str
    labels : List[Label]
    # Github's answer to "last updated at"
    updatedAt : str


# Extract all PRs mentioned in a list of data files.
def _extract_prs(datae: List[dict]) -> List[BasicPRInformation]:
    prs = []
    for data in datae:
        for page in data["output"]:
            for entry in page["data"]["search"]["nodes"]:
                labels = [Label(label["name"], label["color"], label["url"]) for label in entry["labels"]["nodes"]]
                prs.append(BasicPRInformation(
                    entry["number"], entry["author"], entry["title"], entry["url"], labels, entry["updatedAt"]
                ))
    return prs


# Print table entries about a sequence of PRs.
# If 'print_detailed_information' is true, print information about each PR in this list:
# its diff size, number of files modified and number of comments.
# (Some queries, e.g. about badly labelled PR, omit this information.)
def _print_pr_entries(pr_infos: dict, prs : List[BasicPRInformation], print_detailed_information: bool) -> None:
    for pr in prs:
        print("<tr>")
        print("<td>{}</td>".format(pr_link(pr.number, pr.url)))
        print("<td>{}</td>".format(user_link(pr.author)))
        print("<td>{}</td>".format(title_link(pr.title, pr.url)))
        print("<td>")
        for label in pr.labels:
            print(label_link(label))
        print("</td>")
        if print_detailed_information:
            try:
                pr_info = pr_infos[str(pr.number)]
                print("<td>{}/{}</td>".format(pr_info["additions"], pr_info["deletions"]))
                print("<td>{}</td>".format(pr_info["changed_files"]))
                comments = pr_info["comments"] + pr_info["review_comments"]
                print("<td>{}</td>".format(comments))
            except KeyError:
                print("<td>-1/-1</td>\n<td>-1</td>\n<td>-1</td>")
                print(f"PR #{pr.number} is wicked!", file=sys.stderr)
        else:
            print("<td>-1/-1</td>\n<td>-1</td>\n<td>-1</td>")

        print("<td>{}</td>".format(time_info(pr.updatedAt)))
        print("</tr>")


# Print a dashboard of a given list of PRs.
def _print_dashboard(pr_infos: dict, prs : List[BasicPRInformation], kind: PRList, print_detailed_information: bool) -> None:
    # Title of each list, and the corresponding HTML anchor.
    # Explain what each PR list contains upon hovering the heading.
    (id, title) = getIdTitle(kind)
    print(f"<h2 id=\"{id}\"><a href=\"#{id}\" title=\"{long_description(kind)}\">{title}</a></h2>")
    # If there are no PRs, skip the table header and print a bold notice such as
    # "There are currently **no** stale `delegated` PRs. Congratulations!".
    if not prs:
        print(f'There are currently <b>no</b> {short_description(kind)}. Congratulations!\n')
        return

    print("""<table>
    <thead>
    <tr>
    <th>Number</th>
    <th>Author</th>
    <th>Title</th>
    <th>Labels</th>
    <th><a title="number of added/deleted lines">+/-</a></th>
    <th><a title="number of files modified">&#128221;</a></th>
    <th><a title="number of review comments on this PR">&#128172;</a></th>
    <th>Updated</th>
    </tr>
    </thead>""")

    _print_pr_entries(pr_infos, prs, print_detailed_information)

    # Print the footer
    print("</table>")


def print_dashboard(datae : List[dict], kind : PRList) -> None:
    '''`datae` is a list of parsed data files to process'''
    # Print all PRs in all the data files. We use the PR info file to provide additional information.
    with open(sys.argv[1], 'r') as f:
        pr_infos = json.load(f)
        _print_dashboard(pr_infos, _extract_prs(datae), kind, True)


# Print the list of PRs in the review queue, as well as two sub-lists of these:
# all PRs by new contributors, and all PRs labelled 'easy'.
def print_queue_boards(queue_data : List[dict]) -> None:
    queue_prs = _extract_prs(queue_data)
    newcontrib = [prinfo for prinfo in queue_prs if 'new-contributor' in [l.name for l in prinfo.labels]]
    easy = [prinfo for prinfo in queue_prs if 'easy' in [l.name for l in prinfo.labels]]
    with open(sys.argv[1], 'r') as f:
        pr_infos = json.load(f)
        _print_dashboard(pr_infos, queue_prs, PRList.Queue, True)
        _print_dashboard(pr_infos, newcontrib, PRList.QueueNewContributor, True)
        _print_dashboard(pr_infos, easy, PRList.QueueEasy, True)


# Print dashboards of
# - all feature PRs without a topic label,
# - all PRs with a badly formatted title,
# - all PRs with contradictory labels
# among those given in `data` that are not labelled as work in progress.
def print_dashboard_bad_labels_title(data : dict) -> None:
    all_prs = _extract_prs([data])
    # Filter out all PRs with have a WIP label.
    all_prs = [pr for pr in all_prs if not ('WIP' in [l.name for l in pr.labels])]

    with_bad_title = [pr for pr in all_prs if not pr.title.startswith(("feat", "chore", "perf", "refactor", "style", "fix", "doc"))]
    # Whether a PR has a "topic" label.
    def has_topic_label(pr: BasicPRInformation) -> bool:
        topic_labels = [l for l in pr.labels if l.name in ['CI', 'IMO'] or l.name.startswith("t-")]
        return len(topic_labels) >= 1
    prs_without_topic_label = [pr for pr in all_prs if pr.title.startswith("feat") and not has_topic_label(pr)]

    def has_contradictory_labels(pr: BasicPRInformation) -> bool:
        # Combine common labels.
        canonicalise = {
            "ready-to-merge": "bors", "auto-merge-after-CI": "bors",
            "blocked-by-other-PR": "blocked", "blocked-by-core-PR": "blocked", "blocked-by-batt-PR": "blocked", "blocked-by-qq-PR": "blocked",
        }
        normalised_labels = [(canonicalise[l.name] if l.name in canonicalise else l.name) for l in pr.labels]
        # Test for contradictory label combinations.
        if 'awaiting-review-DONT-USE' in normalised_labels:
            return True
        # Waiting for a decision contradicts most other labels.
        elif "awaiting-zulip" in normalised_labels and any(
                [l for l in normalised_labels if l in ["awaiting-author", "delegated", "bors", "WIP"]]):
            return True
        elif "WIP" in normalised_labels and ("awaiting-review" in normalised_labels or "bors" in normalised_labels):
            return True
        elif "awaiting-author" in normalised_labels and "awaiting-zulip" in normalised_labels:
            return True
        elif "bors" in normalised_labels and "WIP" in normalised_labels:
            return True
        return False
    prs_with_contradictory_labels = [pr for pr in all_prs if has_contradictory_labels(pr)]

    # Open the file containing the PR info.
    with open(sys.argv[1], 'r') as f:
        pr_infos = json.load(f)
        _print_dashboard(pr_infos, with_bad_title, PRList.BadTitle, False)
        _print_dashboard(pr_infos, prs_without_topic_label, PRList.Unlabelled, False)
        _print_dashboard(pr_infos, prs_with_contradictory_labels, PRList.ContradictoryLabels, False)


main()
