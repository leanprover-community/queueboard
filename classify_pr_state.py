"""Helper utilities for determining the current state of a pull request from e.g. its labels."""

from datetime import datetime
from enum import Enum, auto
from typing import List, NamedTuple

from dateutil import tz


# The different kinds of PR labels we care about.
# We usually do not care about the precise label names, but just their function.
class LabelKind(Enum):
    WIP = auto()  # the WIP labelled, denoting a PR which is work in progress
    AwaitingCI = auto()
    Review = auto()
    """This PR is ready for review: this label is only added for historical purposes, as mathlib does not use this label any more"""
    HelpWanted = auto()
    '''This PR is labelled help-wanted or please-adopt'''
    Author = auto()
    '''This PR is labelled awaiting-author'''
    MergeConflict = auto()  # merge-conflict
    Blocked = auto()  # blocked-by-other-PR, etc.
    Decision = auto()  # awaiting-zulip
    Delegated = auto()  # delegated
    Bors = auto()  # ready-to-merge or auto-merge-after-CI
    # any other label, such as t-something (but also "easy", "bug" and a few more)
    Other = auto()


# Map a label name (as a string) to a `LabelKind`.
#
# NB. Make sure this mapping reflects the *current* label names on github.
# For historical purposes, it might be necessary to also track their
# historical names: for the current use of this code, this is not an issue.
label_categorisation_rules: dict[str, LabelKind] = {
    "WIP": LabelKind.WIP,
    "awaiting-CI": LabelKind.AwaitingCI,
    "awaiting-review-DONT-USE": LabelKind.Review,
    "awaiting-author": LabelKind.Author,
    "blocked-by-other-PR": LabelKind.Blocked,
    "blocked-by-batt-PR": LabelKind.Blocked,
    "blocked-by-core-PR": LabelKind.Blocked,
    "blocked-by-qq-PR": LabelKind.Blocked,
    "blocked-by-core-relase": LabelKind.Blocked,
    "merge-conflict": LabelKind.MergeConflict,
    "awaiting-zulip": LabelKind.Decision,
    "delegated": LabelKind.Delegated,
    "ready-to-merge": LabelKind.Bors,
    "auto-merge-after-CI": LabelKind.Bors,
    "help-wanted": LabelKind.HelpWanted,
    "please-adopt": LabelKind.HelpWanted,
}


class CIStatus(Enum):
    # All build jobs pass (or are skipped).
    Pass = auto()
    # Some build job fails which is not "inessential" (see below).
    Fail = auto()
    # Some build job fails, but all failing jobs are (usually) spurious failures,
    # or related to defects in the infrastructure.
    # Unless a PR actively modifies such infrastructure, this is not a bug in the PR.
    FailInessential = auto()
    # CI is currently running
    Running = auto()
    # Missing data.
    Missing = auto()

    @staticmethod
    def from_string(s: str):
        return {
            "pass": CIStatus.Pass,
            "fail": CIStatus.Fail,
            "fail-inessential": CIStatus.FailInessential,
            "running": CIStatus.Running,
            None: CIStatus.Missing,
        }[s]


# All relevant state of a PR at each point in time.
class PRState(NamedTuple):
    labels: List[LabelKind]
    ci: CIStatus
    draft: bool
    """True if and only if this PR is marked as draft."""
    from_fork: bool

    @staticmethod
    def with_labels(labels: List[LabelKind]):
        """Create a PR state with just these labels, passing CI and ready for review"""
        return PRState(labels, CIStatus.Pass, False, False)
    @staticmethod
    def with_labels_and_ci(labels: List[LabelKind], ci: CIStatus):
        return PRState(labels, ci, False, False)



# Describes the current status of a pull request in terms of the categories we care about.
class PRStatus(Enum):
    # This PR is marked as work in progress, is in draft state or CI fails.
    # CI running is ignored, as this ought to be intermittent.
    NotReady = auto()
    # This PR is blocked on another PR, to mathlib, core or batteries.
    Blocked = auto()
    AwaitingReview = auto()
    # This PR is labelled help-wanted or please-adopt: it needs some help
    # to be moved along (not just the author finding enough time).
    HelpWanted = auto()
    # Review comments to process: different from "not ready"
    AwaitingAuthor = auto()
    # This PR is blocked on a decision: the awaiting-zulip label signifies this.
    AwaitingDecision = auto()
    # This PR has a merge conflict and is ready, not blocked on another PR,
    # not awaiting author action and and otherwise awaiting review.
    # (Put differently, "blocked", "not ready" or "awaiting-author" take precedence over a merge conflict.)
    MergeConflict = auto()
    # This PR was delegated to the user.
    Delegated = auto()
    # Ready-to-merge or auto-merge-after-CI. Can become stale if CI fails/multiple retries etc.
    AwaitingBors = auto()
    # FIXME: do we actually need this category?
    Closed = auto()
    Contradictory = auto()
    """PR labels are contradictory: we cannot determine easily what this PR's status is"""


def label_to_prstatus(label: LabelKind) -> PRStatus:
    return {
        LabelKind.WIP: PRStatus.NotReady,
        LabelKind.AwaitingCI: PRStatus.NotReady,
        LabelKind.Review: PRStatus.AwaitingReview,
        LabelKind.HelpWanted: PRStatus.HelpWanted,
        LabelKind.Author: PRStatus.AwaitingAuthor,
        LabelKind.Blocked: PRStatus.Blocked,
        LabelKind.MergeConflict: PRStatus.MergeConflict,
        LabelKind.Decision: PRStatus.AwaitingDecision,
        LabelKind.Delegated: PRStatus.Delegated,
        LabelKind.Bors: PRStatus.AwaitingBors,
    }[label]


def determine_PR_status(date: datetime, state: PRState) -> PRStatus:
    """Determine a PR's status from its state
    'date' is necessary as the interpretation of the awaiting-review label changes over time"""
    # TODO: decide what to do with inessential failures for the classification...
    # for infra PRs, just treating it as "fine" seems wrong.
    # Perhaps still treat as failing, but expose differently on a dashboard?
    if state.draft or state.ci in [CIStatus.Fail, CIStatus.FailInessential, CIStatus.Missing]:
        return PRStatus.NotReady
    # The 'awaiting-CI' label or 'running' CI also mark a PR as 'not ready' yet:
    # this ought to be a transient state; when a CI run completes, the PR status
    # (in hindsight) will be set accordingly.
    # (The latter label is checked further down, to enable better detection of contradictory labels.)
    if state.ci == CIStatus.Running:
        return PRStatus.NotReady
    # Ignore all "other" labels, which are not relevant for this anyway.
    labels = [label for label in state.labels if label != LabelKind.Other]

    # Labels can be contradictory (so we need to recognise this).
    # Also note that their priority orders are not transitive!
    # TODO: is this actually a problem for our algorithm?
    # NB. A PR *can* legitimately have *two* labels of a blocked kind, for example,
    # so we *do not* want to deduplicate the kinds here.
    if labels == []:
        # Until July 9th, a PR had to be labelled awaiting-review to be marked as such.
        # After that date, the label is retired and PRs are considered ready for review
        # by default.
        if date > datetime(2024, 7, 9, tzinfo=tz.tzutc()):
            return PRStatus.AwaitingReview
        else:
            return PRStatus.AwaitingAuthor
    elif len(labels) == 1:
        return label_to_prstatus(labels[0])
    else:
        # Some label combinations are contradictory. We mark the PR as in a "contradictory" state.
        # awaiting-decision is exclusive with any of waiting on review, author, delegation and sent to bors.
        contra_to_decision = [
            LabelKind.Author, LabelKind.Review, LabelKind.Delegated, LabelKind.Bors, LabelKind.WIP
        ]
        if LabelKind.Decision in labels and any([label for label in labels if label in contra_to_decision]):
            return PRStatus.Contradictory
        # Work in progress contradicts "awaiting review" and "ready for bors".
        if LabelKind.WIP in labels and any([label for label in labels if label in [LabelKind.Review, LabelKind.Bors]]):
            return PRStatus.Contradictory
        # Waiting for the author and review is also contradictory,
        if LabelKind.Author in labels and LabelKind.Review in labels:
            return PRStatus.Contradictory
        # as is being ready for merge and blocked
        if LabelKind.Bors in labels and LabelKind.Blocked in labels:
            return PRStatus.Contradictory
        # or being ready for merge and looking for help.
        if LabelKind.Bors in labels and LabelKind.HelpWanted in labels:
            return PRStatus.Contradictory

        # If the set of labels is not contradictory, we use a clear priority order:
        # from highest to lowest priority, the label kinds are ordered as
        # blocked > help wanted > WIP > decision > merge conflict > bors > author; review > delegate.
        # We can simply use Python's sorting to find the highest priority label.
        key: dict[LabelKind, int] = {
            LabelKind.Blocked: 11,
            LabelKind.HelpWanted: 10,
            # The next two labels have the same effect, hence the same priority.
            LabelKind.WIP: 9,
            LabelKind.AwaitingCI: 9,
            LabelKind.Decision: 8,
            LabelKind.MergeConflict: 7,
            LabelKind.Bors: 6,
            LabelKind.Author: 5,
            LabelKind.Review: 5,
            LabelKind.Delegated: 4,
        }
        sorted_labels = sorted(labels, key=lambda k: key[k], reverse=True)
        return label_to_prstatus(sorted_labels[0])


def test_determine_status() -> None:
    # NB: this only tests the new handling of awaiting-review status.
    default_date = datetime(2024, 8, 1, tzinfo=tz.tzutc())

    def check(labels: List[LabelKind], expected: PRStatus) -> None:
        state = PRState.with_labels(labels)
        actual = determine_PR_status(default_date, state)
        assert expected == actual, f"expected PR status {expected} from labels {labels}, got {actual}"

    # This version takes a PR state instead.
    def check2(state: PRState, expected: PRStatus) -> None:
        actual = determine_PR_status(default_date, state)
        assert expected == actual, f"expected PR status {expected} from state {state}, got {actual}"

    # Check if the PR status on a given list of labels in one of several allowed values.
    # If successful, returns the actual PR status computed.
    def check_flexible(labels: List[LabelKind], allowed: List[PRStatus]) -> PRStatus:
        state = PRState.with_labels_and_ci(labels, CIStatus.Pass)
        actual = determine_PR_status(default_date, state)
        assert actual in allowed, f"expected PR status in {allowed} from labels {labels}, got {actual}"
        return actual

    # Tests for handling draft and CI state.
    # These take precedence over any other labels.
    # Failing CI marks a PR as "not ready".
    check2(PRState([], CIStatus.Pass, True, False), PRStatus.NotReady)
    check2(PRState([], CIStatus.Fail, False, False), PRStatus.NotReady)
    check2(PRState([], CIStatus.Fail, True, False), PRStatus.NotReady)
    # Running CI is treated as "failing" for the purposes of our classification.
    # The awaiting-CI label has the same effect as a "running" CI state.
    check2(PRState.with_labels_and_ci([], CIStatus.Running), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.AwaitingCI], CIStatus.Pass), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.AwaitingCI], CIStatus.Fail), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.Other], CIStatus.Running), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.Other, LabelKind.AwaitingCI], CIStatus.Running), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.WIP], CIStatus.Fail), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.WIP, LabelKind.AwaitingCI], CIStatus.Fail), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.MergeConflict], CIStatus.Fail), PRStatus.NotReady)

    # Missing CI status is treated as "failing" for the purposes of the classification.
    check2(PRState.with_labels_and_ci([], CIStatus.Missing), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.WIP], CIStatus.Missing), PRStatus.NotReady)
    check2(PRState.with_labels_and_ci([LabelKind.MergeConflict], CIStatus.Missing), PRStatus.NotReady)

    # All label kinds we distinguish.
    ALL = LabelKind._member_map_.values()
    # For each combination of labels, the resulting PR status is either contradictory
    # or the status associated to some label.
    # The order of adding labels does not matter.
    check([], PRStatus.AwaitingReview)
    check([LabelKind.Other], PRStatus.AwaitingReview)
    check([LabelKind.Other, LabelKind.Other], PRStatus.AwaitingReview)
    check([LabelKind.Other, LabelKind.Other, LabelKind.Other], PRStatus.AwaitingReview)
    for a in ALL:
        if a != LabelKind.Other:
            check([a], label_to_prstatus(a))
        for b in ALL:
            statusses = [label_to_prstatus(lab) for lab in [a, b] if lab != LabelKind.Other]
            # The "other" kind has no associated PR state: continue if all labels are "other"
            if not statusses:
                continue
            actual = check_flexible([a, b], statusses + [PRStatus.Contradictory])
            check([b, a], actual)
            result_ab = actual
            for c in ALL:
                # Adding further labels to some contradictory status remains contradictory.
                if result_ab == PRStatus.Contradictory:
                    check([a, b, c], PRStatus.Contradictory)
                else:
                    statusses = [label_to_prstatus(lab) for lab in [a, b, c] if lab != LabelKind.Other]
                    if not statusses:
                        continue
                    actual = check_flexible([a, b, c], statusses + [PRStatus.Contradictory])
                    check([a, c, b], actual)
                    check([b, a, c], actual)
                    check([b, c, a], actual)
                    check([c, a, b], actual)
                    check([c, b, a], actual)
    # One specific sanity check, which fails in the previous implementation.
    check([LabelKind.Blocked, LabelKind.Review], PRStatus.Blocked)
    check([LabelKind.Review, LabelKind.Blocked], PRStatus.Blocked)
    print("test_determine_status: all tests pass")


if __name__ == '__main__':
    test_determine_status()
