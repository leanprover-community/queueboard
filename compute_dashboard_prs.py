#!/usr/bin/env python3

"""
This file contains the code for computing the PRs on each dashboard in |mathlib_dashboards.py|.

"""

from datetime import datetime, timedelta, timezone
from enum import Enum, auto, unique
import json
from dateutil import parser, relativedelta
from typing import List, NamedTuple, Tuple

from ci_status import CIStatus
from classify_pr_state import (PRState, PRStatus,
                               determine_PR_status, label_categorisation_rules)
from mathlib_dashboards import Dashboard, short_description, long_description, getIdTitle
from util import my_assert_eq, format_delta, timedelta_tryParse, relativedelta_tryParse


# The following structures are completely project-agnostic.

# The information we need about each PR label: its name, background colour and URL
class Label(NamedTuple):
    name: str
    """This label's background colour, as a six-digit hexadecimal code"""
    color: str
    url: str


# Basic information about a PR: does not contain the diff size, which is contained in pr_info.json instead.
class BasicPRInformation(NamedTuple):
    number: int  # PR number, non-negative
    # Just the author's github handle; the corresponding URL is determined automatically.
    # For dependabot PRs, this can be `None` due to quirks in the data returned by Github's REST API.
    author_name: str | None
    title: str
    url: str
    labels: List[Label]
    # Github's answer to "last updated at"
    updatedAt: datetime


# Extract all PRs mentioned in a data file.
def _extract_prs(data: dict) -> List[BasicPRInformation]:
    prs = []
    for page in data["output"]:
        for entry in page["data"]["search"]["nodes"]:
            name = None
            if "login" not in entry["author"]:
                print(
                    f'warning: missing author information for PR {entry["number"]}, its authors dictionary is {entry["author"]} --- was this submitted by dependabot?',
                    file=sys.stderr,
                )
            else:
                name = entry["author"]["login"]
            labels = [Label(label["name"], label["color"], label["url"]) for label in entry["labels"]["nodes"]]

            prs.append(BasicPRInformation(entry["number"], name, entry["title"], entry["url"], labels, parser.isoparse(entry["updatedAt"])))
    return prs


class DataStatus(Enum):
    Valid = auto()
    Incomplete = auto()
    # This can happen if a PR is stubborn (i.e. no events data is collected)
    # or a PR's data is contradictory (hence ignored).
    Missing = auto()

class LastStatusChange(NamedTuple):
    status: DataStatus
    time: datetime
    delta: relativedelta.relativedelta
    current_status: PRStatus

class TotalQueueTime(NamedTuple):
    status: DataStatus
    value_td: timedelta
    value_rd: relativedelta.relativedelta
    explanation: str

# All information about a single PR contained in `open_pr_info.json`.
# Keep this in sync with the actual file, extending this once new data is added!
class AggregatePRInfo(NamedTuple):
    is_draft: bool
    CI_status: CIStatus
    # The branch this PR is opened against: should be 'master' (for most PRs)
    base_branch: str
    # The repository this PR was opened from: should be 'leanprover-community',
    # otherwise it is a PR from a fork.
    head_repo: str
    # 'open' for open PRs, 'closed' for closed PRs
    state: str
    # Github's time when the PR was "last updated"
    last_updated: datetime
    # The PR author's github handle
    author: str
    title: str
    # All labels assigned to this PR.
    labels: List[Label]
    additions: int
    deletions: int
    number_modified_files: int
    # Github handles of all users (if any) approving this
    approvals: List[str]
    # The github handles of all users (if any) assigned to this PR
    assignees: List[str]
    # This field is *not* present if there is only "basic" information about this PR
    number_total_comments: int | None
    # The following fields are not present when there is only basic information about this PR.
    # They are also missing if a PR's events data is invalid (because github returned bogus results).
    # Otherwise, they include their validity status ("missing", "incomplete", "valid").
    last_status_change: LastStatusChange | None
    first_on_queue: Tuple[DataStatus, datetime | None] | None
    total_queue_time: TotalQueueTime | None

# Missing aggregate information will be replaced by this default item.
PLACEHOLDER_AGGREGATE_INFO = AggregatePRInfo(
    False, CIStatus.Missing, "master", "leanprover-community", "open", datetime.now(timezone.utc),
    "unknown", "unknown title", [], -1, -1, -1, [], [], None, None, None, None,
)


# Compute the status of each PR in a given list. Return a dictionary keyed by the PR number.
# (`BasicPRInformation` is not hashable, hence cannot be used as a dictionary key.)
# 'aggregate_info' contains aggregate information about each PR's CI state,
# draft status and base branch (and more, which we do not use).
# If no detailed information was available for a given PR number, 'None' is returned.
def compute_pr_statusses(aggregate_info: dict[int, AggregatePRInfo], prs: List[BasicPRInformation]) -> dict[int, PRStatus]:
    def determine_status(aggregate_info: AggregatePRInfo) -> PRStatus:
        # Ignore all "other" labels, which are not relevant for this anyway.
        labels = [label_categorisation_rules[lab.name] for lab in aggregate_info.labels if lab.name in label_categorisation_rules]
        from_fork = aggregate_info.head_repo != "leanprover-community"
        state = PRState(labels, aggregate_info.CI_status, aggregate_info.is_draft, from_fork)
        return determine_PR_status(datetime.now(timezone.utc), state)

    return {info.number: determine_status(aggregate_info[info.number] or PLACEHOLDER_AGGREGATE_INFO) for info in prs}


# Does a PR have a given label?
def _has_label(pr: BasicPRInformation, name: str) -> bool:
    return name in [label.name for label in pr.labels]


# Extract all PRs from a given list which have a certain label.
def prs_with_label(prs: List[BasicPRInformation], label_name: str) -> List[BasicPRInformation]:
    return [prinfo for prinfo in prs if _has_label(prinfo, label_name)]


# Extract all PRs from a given list which have any label in a certain list.
def prs_with_any_label(prs: List[BasicPRInformation], label_names: List[str]) -> List[BasicPRInformation]:
    return [prinfo for prinfo in prs if any([_has_label(prinfo, name) for name in label_names])]


# Extract all PRs from a given list which do not have a certain label.
def prs_without_label(prs: List[BasicPRInformation], label_name: str) -> List[BasicPRInformation]:
    return [prinfo for prinfo in prs if not _has_label(prinfo, label_name)]


# Extract all PRs from a given list which do not have any label among a given list.
def prs_without_any_label(prs: List[BasicPRInformation], label_names: List[str]) -> List[BasicPRInformation]:
    return [prinfo for prinfo in prs if all([not _has_label(prinfo, name) for name in label_names])]


# The following logic is mathlib-dependent again.


def has_contradictory_labels(pr: BasicPRInformation) -> bool:
    # Combine common labels.
    canonicalise = {
        "ready-to-merge": "bors", "auto-merge-after-CI": "bors",
        "blocked-by-other-PR": "blocked", "blocked-by-core-PR": "blocked", "blocked-by-batt-PR": "blocked", "blocked-by-qq-PR": "blocked",
    }
    normalised_labels = [(canonicalise[label.name] if label.name in canonicalise else label.name) for label in pr.labels]
    # Test for contradictory label combinations.
    if "awaiting-review-DONT-USE" in normalised_labels:
        return True
    elif "bors" in normalised_labels and ("awaiting-author" in normalised_labels or "awaiting-zulip" in normalised_labels or "WIP" in normalised_labels):
        return True
    elif "WIP" in normalised_labels and "awaiting-review" in normalised_labels:
        return True
    return False


# Determine all PRs in `prs` which are not labelled `WIP` and
# - are feature PRs without a topic label,
# - have a badly formatted title (we currently only check some of the conditions in the guidelines),
# - have contradictory labels.
def compute_dashboards_bad_labels_title(
    prs: List[BasicPRInformation],
) -> Tuple[List[BasicPRInformation], List[BasicPRInformation], List[BasicPRInformation]]:
    # Filter out all PRs which have a WIP label.
    nonwip_prs = prs_without_label(prs, "WIP")
    with_bad_title = [pr for pr in nonwip_prs if not pr.title.startswith(("feat", "chore", "perf", "refactor", "style", "fix", "doc"))]

    # Whether a PR has a "topic" label.
    def has_topic_label(pr: BasicPRInformation) -> bool:
        topic_labels = [label for label in pr.labels if label.name in ["CI", "IMO"] or label.name.startswith("t-")]
        return len(topic_labels) >= 1

    prs_without_topic_label = [pr for pr in nonwip_prs if pr.title.startswith("feat") and not has_topic_label(pr)]
    prs_with_contradictory_labels = [pr for pr in nonwip_prs if has_contradictory_labels(pr)]
    return (with_bad_title, prs_without_topic_label, prs_with_contradictory_labels)


# use_aggregate_queue: if True, determine the review queue (and everything depending on it)
# from the aggregate data and not queue.json
def determine_pr_dashboards(
    nondraft_PRs: List[BasicPRInformation],
    base_branch: dict[int, str],
    prs_from_fork: List[BasicPRInformation],
    CI_status: dict[int, CIStatus],
    aggregate_info: dict[int, AggregatePRInfo],
    use_aggregate_queue: bool,
) -> dict[Dashboard, List[BasicPRInformation]]:
    approved = [pr for pr in nondraft_PRs if aggregate_info[pr.number].approvals]
    prs_to_list: dict[Dashboard, List[BasicPRInformation]] = dict()
    # The 'tech debt', 'other base' and 'from fork' boards are obtained
    # from filtering the list of all non-draft PRs (without the WIP label).
    all_ready_prs = prs_without_label(nondraft_PRs, "WIP")
    prs_to_list[Dashboard.TechDebt] = prs_with_any_label(all_ready_prs, ["tech debt", "longest-pole"])
    prs_to_list[Dashboard.OtherBase] = [pr for pr in nondraft_PRs if base_branch[pr.number] != "master"]
    prs_to_list[Dashboard.FromFork] = prs_from_fork

    prs_to_list[Dashboard.NeedsHelp] = prs_with_any_label(nondraft_PRs, ["help-wanted", "please_adopt"])
    prs_to_list[Dashboard.NeedsDecision] = prs_with_label(nondraft_PRs, "awaiting-zulip")

    # Compute all PRs on the review queue (and well as several sub-filters).
    # The review queue consists of all PRs against the master branch, with passing CI,
    # that are not in draft state and not labelled WIP, help-wanted or please-adopt,
    # and have none of the other labels below.
    master_prs_with_CI = [pr for pr in nondraft_PRs if base_branch[pr.number] == "master" and (CI_status[pr.number] == CIStatus.Pass)]
    master_CI_notfork = [pr for pr in master_prs_with_CI if pr not in prs_from_fork]
    other_labels = [
        # XXX: does the #queue check for all of these labels?
        "blocked-by-other-PR",
        "blocked-by-core-PR",
        "blocked-by-batt-PR",
        "blocked-by-qq-PR",
        "awaiting-CI",
        "awaiting-author",
        "awaiting-zulip",
        "please-adopt",
        "help-wanted",
        "WIP",
        "delegated",
        "auto-merge-after-CI",
        "ready-to-merge",
    ]
    queue_or_merge_conflict = prs_without_any_label(master_CI_notfork, other_labels)
    prs_to_list[Dashboard.NeedsMerge] = prs_with_label(queue_or_merge_conflict, "merge-conflict")
    queue_prs = prs_without_label(queue_or_merge_conflict, "merge-conflict")

    interesting_CI = [pr for pr in nondraft_PRs if CI_status[pr.number] == CIStatus.FailInessential]
    foo = [pr for pr in interesting_CI if base_branch[pr.number] == "master" and pr not in prs_from_fork]
    prs_to_list[Dashboard.InessentialCIFails] = prs_without_any_label(foo, other_labels + ["merge-conflict"])

    queue_prs2 = None
    with open("queue.json", "r") as queuefile:
        queue_prs2 = _extract_prs(json.load(queuefile))
        queue_pr_numbers2 = [pr.number for pr in queue_prs2]
    msg = "comparing this page's review dashboard (left) with the Github #queue (right)"
    if my_assert_eq(msg, [pr.number for pr in queue_prs], queue_pr_numbers2):
        print("Review dashboard and #queue match, hooray!", file=sys.stderr)

    prs_to_list[Dashboard.Queue] = queue_prs if use_aggregate_queue else queue_prs2
    queue = prs_to_list[Dashboard.Queue]
    prs_to_list[Dashboard.QueueNewContributor] = prs_with_label(queue, "new-contributor")
    prs_to_list[Dashboard.QueueEasy] = prs_with_label(queue, "easy")
    prs_to_list[Dashboard.QueueTechDebt] = prs_with_any_label(queue, ["tech debt", "longest-pole"])

    a_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    a_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)
    one_day_stale = [pr for pr in nondraft_PRs if aggregate_info[pr.number].last_updated < a_day_ago]
    one_week_stale = [pr for pr in nondraft_PRs if aggregate_info[pr.number].last_updated < a_week_ago]
    prs_to_list[Dashboard.AllReadyToMerge] = prs_with_any_label(nondraft_PRs, ["ready-to-merge", "auto-merge-after-CI"])
    prs_to_list[Dashboard.StaleReadyToMerge] = prs_with_any_label(one_day_stale, ["ready-to-merge", "auto-merge-after-CI"])
    prs_to_list[Dashboard.StaleDelegated] = prs_with_label(one_day_stale, "delegated")
    mm_prs = prs_with_label(one_day_stale, "maintainer-merge")
    prs_to_list[Dashboard.StaleMaintainerMerge] = prs_without_label(mm_prs, "ready-to-merge")
    prs_to_list[Dashboard.AllMaintainerMerge] = prs_without_label(prs_with_label(nondraft_PRs, "maintainer-merge"), "ready-to-merge")
    prs_to_list[Dashboard.StaleNewContributor] = prs_with_label(one_week_stale, "new-contributor")

    stale_queue = []
    for pr in queue:
        last_real_update = aggregate_info[pr.number].last_status_change
        if last_real_update is not None and last_real_update.time < two_weeks_ago:
            stale_queue.append(pr)
    prs_to_list[Dashboard.QueueStaleUnassigned] = [pr for pr in stale_queue if not aggregate_info[pr.number].assignees]
    # TODO/Future: use a more refined measure of activity!
    prs_to_list[Dashboard.QueueStaleAssigned] = [pr for pr in stale_queue if aggregate_info[pr.number].assignees]

    (bad_title, unlabelled, contradictory) = compute_dashboards_bad_labels_title(nondraft_PRs)
    prs_to_list[Dashboard.BadTitle] = bad_title
    prs_to_list[Dashboard.Unlabelled] = unlabelled
    prs_to_list[Dashboard.ContradictoryLabels] = contradictory
    prs_to_list[Dashboard.Approved] = approved
    return prs_to_list
