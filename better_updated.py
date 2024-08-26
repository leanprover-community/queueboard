"""
# Computing a better estimate how long a PR was been awaiting review.

**Problem** We would like a way to track the progress of PRs, and especially learn which PRs
have been waiting long for review. Currently, we have no good way of obtaining this information:
we use the crude heuristic of
"this PR was last updated X ago, and is awaiting review now" as a metric for "waiting for time X".

That metric is imperfect because
- not everything "updating" a PR is meaningful for our purposes
If somebody edits the PR description to describe the change better
or tweaks the code to make it better understood --- without other activity
and not in response to feedback --- that is a good thing,
but does not change the PR's review status.
- a PR's time on the review queue is often interrupted by having merge conflicts.
This is usually only a temporary state, but means long streaks of no changes are much more rare.
In particular, this disadvantages conflict-prone PRs.

**A better metric** would be to track the PRs state over time, and compute
e.g. the total amount of time this PR was awaiting review.
This is what we attempt to do.

## Input data
This algorithm process a sequence of events "on X, this PR changed in this and that way"
and returns a list of all times when the PRs state changed:
for the purposes of our analysis, this could be "a PR became blocked on another PR",
"a PR became unblocked", "a PR was marked as waiting on author", "a PR incurred a merge conflict".

From this information, we can compute the total time a PR was waiting for review, for instance.

## Implementation notes

This algorithm is just a skeleton: it contains the *analysis* of the given input data,
but does not parse the input data from any other input. (That is a second step.)

As an initial prototype, this file makes a number of simplifying assumptions:
1. We omit changes of the PR status between "draft" and "regular".
2. We also ignore changes of the CI status (between "passing", "running" and "failing"),
and pretend for now that every PR is passing all the time.
"""

from datetime import datetime, timedelta
from enum import Enum, auto
from typing import List, NamedTuple, Tuple

############# PR state: the relevant pieces of PR state we care about #########


# The different kinds of PR labels we care about.
# We usually do not care about the precise label names, but just their function.
class LabelKind(Enum):
    WIP = auto()  # WIP
    Review = auto()
    """This PR is ready for review: this label is only added for historical purposes, as mathlib does not use this label any more"""
    Author = auto()  # awaiting-author
    MergeConflict = auto()  # merge-conflict
    Blocked = auto()  # blocked-by-other-PR, etc.
    Decision = auto()  # awaiting-zulip
    Delegated = auto()  # delegated
    Bors = auto()  # ready-to-merge or auto-merge-after-CI
    # any other label, such as t-something (but also "easy", "bug" and a few more)
    Other = auto()


class CIStatus(Enum):
    Pass = auto()
    Fail = auto()
    Running = auto()


# All relevant state of a PR at each point in time.
class PRState(NamedTuple):
    labels: List[LabelKind]
    ci: CIStatus
    draft: bool


# Something changed on a PR which we care about:
# - a new label got added or removed
# - the PR was (un)marked draft: omitting this for now
# - the PR status changed (passing or failing to build)
#
# The most elegant design would be using sum types, i.e. encoding the data for
# each variant directly within the enum.
# As Python does not have these, we use a dictionary of extra data.
class PRChange(Enum):
    LabelAdded = auto()
    """A new label got added"""

    LabelRemoved = auto()
    """An existing label got removed"""

    # FIXME: we ignore this for now
    ToggleDraftStatus = auto()
    """This PR's draft status changed"""

    # FIXME: we ignore this for now
    CIStatusChanged = auto()
    """This's PR's CI state changed"""

# XXX: does github produce events like "labels xyz got added and wpq got removed"?
# If so, need to process these separately or something... we will see!
# For now, pretend these are separate events.


# Something changed on this PR.
class Event(NamedTuple):
    time: datetime
    change: PRChange
    # Additional details about what changed.
    # For ToggleDraftStatus and CIStatusChanged, this will be empty for now.
    # For Label{Added,Removed}, this will contain the name of all label(s)
    # added and removed, respectively.
    extra: dict


# Update the current PR state in light of some change.
def update_state(current: PRState, ev: Event) -> PRState:
    #print(f"current state is {current}, incoming event is {ev}")
    if ev.change == PRChange.ToggleDraftStatus:
        return PRState(current.labels, current.ci, not current.draft)
    elif ev.change == PRChange.CIStatusChanged:
        # FUTURE: we ignore changes of the PR status for now
        return current
    elif ev.change == PRChange.LabelAdded:
        # Depending on the label added, update the PR status.
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            label_kind = label_categorisation_rules[lname]
            return PRState(current.labels + [label_kind], current.ci, current.draft)
        else:
            # Adding an irrelevant label does not change the PR status.
            if not lname.startswith("t-") and lname != "CI":
                print(f"found irrelevant label: {lname}")
            return current
    elif ev.change == PRChange.LabelRemoved:
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            # NB: make sure to *copy* current.labels using [:], otherwise that state is also modified!
            new_labels = current.labels[:]
            new_labels.remove(label_categorisation_rules[lname])
            return PRState(new_labels, current.ci, current.draft)
        else:
            # Removing an irrelevant label does not change the PR status.
            return current
    else:
        print(f"unhandled event variant {ev.change}")
        assert False


# Determine the evolution of this PR's state over time.
# Return a list of pairs (timestamp, s), where this PR moved into state *s* at time *timestamp*.
# The first item corresponds to the PR's creation.
def determine_state_changes(
    creation_time: datetime, events: List[Event]
) -> List[Tuple[datetime, PRState]]:
    result = []
    #print(f"determine_state_changes: events passed are {events}")
    # XXX: we currently assume the PR was created in passing state, not in draft mode
    # and with no labels. (Otherwise, this function expects a "label change" event right at the beginning.)
    curr_state = PRState([], CIStatus.Pass, False)
    result.append((creation_time, curr_state))
    for event in events:
        #print(event.time)
        new_state = update_state(curr_state, event)
        result.append((event.time, new_state))
        curr_state = new_state
        #print(f"appended state is {result}")
    #print(f"determine_state_changes: result is {result}")
    return result


######## PR status: determine a PR's status from its current state #######


# Describes the current status of a pull request in terms of the categories we care about.
class PRStatus(Enum):
    # This PR is marked as work in progress.
    # FUTURE: if this PR is marked as draft or CI fails (or just: fails initially?), also mark as such.
    NotReady = auto()
    # This PR is blocked on another PR, to mathlib, core or batteries.
    Blocked = auto()
    AwaitingReview = auto()
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
    """PR labels are contradictory: we cannot determine easily what this PR's status is"""
    Contradictory = auto()


# Map a label name (as a string) to a `LabelKind`.
#
# NB. Make sure this mapping reflects the *current* label names on github.
# When a label gets renamed, all occurrences are renamed to match, including
# historical ones --- so we need not worry about this.
label_categorisation_rules: dict[str, LabelKind] = {
    "WIP": LabelKind.WIP,
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
}


def label_to_prstatus(label: LabelKind) -> PRStatus:
    return {
        LabelKind.WIP: PRStatus.NotReady,
        LabelKind.Review: PRStatus.AwaitingReview,
        LabelKind.Author: PRStatus.AwaitingAuthor,
        LabelKind.Blocked: PRStatus.Blocked,
        LabelKind.MergeConflict: PRStatus.MergeConflict,
        LabelKind.Decision: PRStatus.AwaitingDecision,
        LabelKind.Delegated: PRStatus.Delegated,
        LabelKind.Bors: PRStatus.AwaitingBors,
    }[label]


# An old fragment, trying to create a perfect "ordering" among all possible labels
# (about which label is "most significant" about the PR's state). Sadly, the list below
# yields a non-transitive "order", which means the *order* in which labels are added
# makes a difference. Hence, we settled on a simpler (but transitive) scheme instead.

# Basic set-up is as below: no and only one label is easy; exclude contradictory labels first.
# Algorithm here is: find the "maximal" label if there are several; then return the
# corresponding state.
# # Any item is equal it itself.
# # Store all pairs (kind, kind2) where 'kind' has lower prior
# # than 'kind2' for determining this PR's status.
# lower_than: List[Tuple[LabelKind, LabelKind]] = [
#     # "Blocked" tages priority over most other labels.
#     (LabelKind.Author, LabelKind.Blocked),
#     (LabelKind.Review, LabelKind.Blocked),
#     (LabelKind.Decision, LabelKind.Blocked),
#     (LabelKind.MergeConflict, LabelKind.Blocked),
#     (LabelKind.WIP, LabelKind.Blocked),
#     # A PR should be **not** be marked ready-for-merge and b
#     # Weird combination, but could make sense.
#     (LabelKind.Delegated, LabelKind.Blocked),
#     # A merge conflict takes priority over waiting on author
#     (LabelKind.Author, LabelKind.MergeConflict),
#     (LabelKind.Review, LabelKind.MergeConflict),
#     (LabelKind.Delegated, LabelKind.MergeConflict),
#     (LabelKind.Bors, LabelKind.MergeConflict),
#     # "Waiting for decision" takes priority over a merge con
#     # as does "work in progress".
#     # NB. This makes our relation non-transitive, as it is r
#     # by definition, but satisfies WIP < Author > Bors > Mer
#     # We *can* deal with that, though.
#     (LabelKind.MergeConflict, LabelKind.Decision),
#     (LabelKind.MergeConflict, LabelKind.WIP),
#     # "Waiting for a decision" contradicts the remaining lab
#     # Sent to bors takes priority over awaiting review, auth
#     # Bors and WIP are contradictory and excluded above.
#     # FIXME: In practice, these combinations can occur with
#     # in which case this labelling should be reversed. Revis
#     (LabelKind.Author, LabelKind.Bors),
#     (LabelKind.Review, LabelKind.Bors),
#     (LabelKind.Bors, LabelKind.Delegated),
#     # Waiting for review and delegated *can* make sense, if
#     # as can 'WIP' and delegated.
#     (LabelKind.Delegated, LabelKind.Review),
#     (LabelKind.Review, LabelKind.WIP),
#     (LabelKind.WIP, LabelKind.Author),
#     (LabelKind.Delegated, LabelKind.Author),
#     # Awaiting review and author is contradictory, as is WIP
# ]
# # Should have 8 choose 2 pairs; 9 of them are excluded above
# assert len(lower_than) + 9 == 28
# # TODO: implement the final decision: compute a min of all k
# print("two label kinds, that is confusing; omitted for now")
# return PRStatus.Closed  # TODO, placeholder!


# Determine a PR's status just from its labels.
# FUTURE: also take the PRs CI status and draft status into account.
def determine_PR_status(date: datetime, labels: List[LabelKind]) -> PRStatus:
    # Ignore all "other" labels, which are not relevant for this anyway.
    labels = [l for l in labels if l != LabelKind.Other]

    # Labels can be contradictory (so we need to recognise this).
    # Also note that their priority orders are not transitive!
    # TODO: is this actually a problem for our algorithm?
    # NB. A PR *can* legitimately have *two* labels of a blocked kind, for example,
    # so we *do not* want to deduplicate the kinds here.
    if labels == []:
        # Until July 9th, a PR had to be labelled awaiting-review to be marked as such.
        # After that date, the label is retired and PRs are considered ready for review
        # by default.
        if date > datetime(2024, 7, 9):
            return PRStatus.AwaitingReview
        else:
            return PRStatus.AwaitingAuthor
    elif len(labels) == 1:
        return label_to_prstatus(labels[0])
    else:
        # Some label combinations are contradictory. We mark the PR as in a "contradictory" state.
        # awaiting-decision is exclusive with any of waiting on review, author, delegation and sent to bors.
        if LabelKind.Decision in labels and any([l for l in labels if
                l in [LabelKind.Author, LabelKind.Review, LabelKind.Delegated, LabelKind.Bors, LabelKind.WIP]]):
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory
        # Work in progress contradicts "awaiting review" and "ready for bors".
        if LabelKind.WIP in labels and any([l for l in labels if l in [LabelKind.Review, LabelKind.Bors]]):
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory
        # Waiting for the author and review is also contradictory,
        if LabelKind.Author in labels and LabelKind.Review in labels:
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory
        # as is being ready-for-merge and blocked.
        if LabelKind.Bors in labels and LabelKind.Blocked in labels:
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory

        # If the set of labels is not contradictory, we use a clear priority order:
        # from highest to lowest priority, the label kinds are ordered as
        # blocked > WIP > merge conflict > bors > decision > author; review > delegate.
        # We can simply use Python's sorting to find the highest priority label.
        key: dict[LabelKind, int] = {
            LabelKind.Blocked: 10,
            LabelKind.WIP: 9,
            LabelKind.MergeConflict: 8,
            LabelKind.Bors: 7,
            LabelKind.Decision: 6,
            LabelKind.Author: 5,
            LabelKind.Review: 5,
            LabelKind.Delegated: 4,
        }
        sorted_labels = sorted(labels, key=lambda k: key[k], reverse=True)
        return label_to_prstatus(sorted_labels[0])


# Determine the evolution of this PR's status over time.
# Return a list of pairs (timestamp, s), where this PR moved into status *s* at time *timestamp*.
# The first item corresponds to the PR's creation.
def determine_status_changes(
    creation_time: datetime, events: List[Event]
) -> List[Tuple[datetime, PRStatus]]:
    evolution = determine_state_changes(creation_time, events)
    #print(f"state changes are {evolution}")
    res = []
    for time, state in evolution:
        res.append((time, determine_PR_status(time, state.labels)))
    return res


########### Final summing up #########


# Determine the total amount of time this PR was awaiting review.
#
# FUTURE ideas for tweaking this reporting:
#  - ignore short intervals of merge conflicts, say less than a day?
#  - ignore short intervals of CI running (if successful before and after)?
def total_queue_time(
    creation_time: datetime, now: datetime, events: List[Event]
) -> timedelta:
    total = timedelta(0)
    evolution_status = determine_status_changes(creation_time, events)
    #print(f"status changes are {evolution_status}")
    # first entry is the PR creation, as a separate event
    assert len(evolution_status) == len(events) + 1
    for i in range(len(evolution_status) - 1):
        (old_time, old_status) = evolution_status[i]
        (new_time, _new_status) = evolution_status[i + 1]
        if old_status == PRStatus.AwaitingReview:
            total += new_time - old_time
    (last, last_status) = evolution_status[-1]
    if last_status == PRStatus.AwaitingReview:
        total += now - last
    return total


# FUTURE: the following is nice API to expose to the dashboard itself
# A better estimate for "when was this PR updated", namely the total amount of time
# this PR was waiting for review. 'number' is the PR's number,
# 'data' the file with all PR data we have.
def better_updated_at(number: int, data):  # -> timedelta:
    pass  # TODO


# TODO: add sanity check if a never-added label is removed


######### Some basic unit tests ##########

# Helper methods to reduce boilerplate


def april(n: int) -> datetime:
    return datetime(2024, 4, n)


def sep(n: int) -> datetime:
    return datetime(2024, 9, n)


def add_label(time: datetime, name: str) -> Event:
    return Event(time, PRChange.LabelAdded, {"name": name})


def remove_label(time: datetime, name: str) -> Event:
    return Event(time, PRChange.LabelRemoved, {"name": name})


# These tests are just some basic smoketests and not exhaustive.
def test_determine_state_changes() -> None:
    def check(events: List[Event], expected: PRState) -> None:
        compute = determine_state_changes(datetime(2024, 7, 15), events)
        actual = compute[-1][1]
        assert expected == actual, f"expected PR state {expected} from events {events}, got {actual}"
    check([], PRState([], CIStatus.Pass, False))
    dummy = datetime(2024, 7, 2)
    check([add_label(dummy, "WIP")], PRState([LabelKind.WIP], CIStatus.Pass, False))
    check([add_label(dummy, "awaiting-author")], PRState([LabelKind.Author], CIStatus.Pass, False))
    # Non-relevant labels are not recorded here.
    check([add_label(dummy, "t-data")], PRState([], CIStatus.Pass, False))
    check([add_label(dummy, "t-data"), add_label(dummy, "WIP")], PRState([LabelKind.WIP], CIStatus.Pass, False))
    check([add_label(dummy, "t-data"), add_label(dummy, "WIP"), remove_label(dummy, "t-data")], PRState([LabelKind.WIP], CIStatus.Pass, False))
    # Adding two labels.
    check([add_label(dummy, "awaiting-author")], PRState([LabelKind.Author], CIStatus.Pass, False))
    check([add_label(dummy, "awaiting-author"), add_label(dummy, "WIP")], PRState([LabelKind.Author, LabelKind.WIP], CIStatus.Pass, False))
    check([add_label(dummy, "awaiting-author"), remove_label(dummy, "awaiting-author")], PRState([], CIStatus.Pass, False))
    check([add_label(dummy, "awaiting-author"), remove_label(dummy, "awaiting-author"), add_label(dummy, "awaiting-zulip")], PRState([LabelKind.Decision], CIStatus.Pass, False))


def test_determine_status() -> None:
    # NB: this only tests the new handling of awaiting-review status.
    default_date = datetime(2024, 8, 1)
    def check(labels: List[LabelKind], expected: PRStatus) -> None:
        actual = determine_PR_status(default_date, labels)
        assert expected == actual, f"expected PR status {expected} from labels {labels}, got {actual}"
    # Check if the PR status on a given list of labels in one of several allowed values.
    # If successful, returns the actual PR status computed.
    def check_flexible(labels: List[LabelKind], allowed: List[PRStatus]) -> PRStatus:
        actual = determine_PR_status(default_date, labels)
        assert actual in allowed, f"expected PR status in {allowed} from labels {labels}, got {actual}"
        return actual

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
            statusses = [label_to_prstatus(l) for l in [a, b] if l != LabelKind.Other]
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
                    statusses = [label_to_prstatus(l) for l in [a, b, c] if l != LabelKind.Other]
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


def smoketest() -> None:
    def check_basic(created: datetime, now:datetime, events: List[Event], expected: timedelta) -> None:
        wait = total_queue_time(created, now, events)
        assert wait == expected, f"basic test failed: expected total time of {expected} in review, obtained {wait} instead"

    # these pass and behave well
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR')], timedelta(days=0))
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), add_label(sep(6), 'merge-conflict')], timedelta(days=0))

    # adding and removing a label yields a BUG: all intermediate lists of labels are empty
    # fixed now, wohoo!
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), remove_label(sep(6), "blocked-by-other-PR")], timedelta(days=4))
    # the add_label afterwards was and is fine
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), remove_label(sep(6), "blocked-by-other-PR"), add_label(sep(8), "WIP")], timedelta(days=2))

    # trying a variant
    check_basic(sep(1), sep(20), [add_label(sep(1), 'blocked-by-other-PR'), remove_label(sep(8), 'blocked-by-other-PR'), add_label(sep(10), 'WIP')], timedelta(days=2))
    # current failure, minimized
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), remove_label(sep(8), 'blocked-by-other-PR')], timedelta(days=2))

    # Doing nothing in April: not ready for review. In September, it is!
    check_basic(april(1), april(3), [], timedelta(days=0))
    check_basic(sep(1), sep(3), [], timedelta(days=2))
    # Applying an irrelevant label.
    check_basic(sep(1), sep(5), [add_label(sep(1), "CI")], timedelta(days=4))
    # Removing it again.
    check_basic(
        sep(1), sep(12),
        [add_label(sep(1), "CI"), remove_label(sep(3), "CI")],
        timedelta(days=11),
    )

    # After September 8th, this PR is in WIP status -> only seven days in review.
    check_basic(sep(1), sep(10), [add_label(sep(1), 'CI'), remove_label(sep(3), 'CI'), add_label(sep(8), 'WIP')], timedelta(days=7))

    # A PR getting blocked.
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), add_label(sep(8), 'easy')], timedelta(days=0))
    # A PR getting unblocked again.
    check_basic(sep(1), sep(10), [add_label(sep(1), 'blocked-by-other-PR'), remove_label(sep(8), 'blocked-by-other-PR')], timedelta(days=2))

    # xxx Applying two irrelevant labels.
    # then removing one...
    # more complex tests to come!


# test_determine_state_changes()
# test_determine_status()
smoketest()
