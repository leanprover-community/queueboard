"""
# Computing a better estimate how long a PR was been awaiting review.

**Problem.** We would like a way to track the progress of PRs, and especially learn which PRs
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
"""

from datetime import datetime, timezone
from enum import Enum, auto
from typing import List, NamedTuple, Tuple

from dateutil import parser, tz
from dateutil.relativedelta import relativedelta

from classify_pr_state import (CIStatus, LabelKind, PRState, PRStatus,
                               determine_PR_status, label_categorisation_rules,
                               label_to_prstatus)


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

    LabelAddedRemoved = auto()
    '''A set of labels was added, and some set of labels was removed
    Note that a given label can be added and removed at the same time'''

    MarkedDraft = auto()
    """This PR was marked as draft"""
    MarkedReady = auto()
    """This PR was marked as ready for review"""

    CIStatusChanged = auto()
    """This PR's CI state changed"""


# Something changed on this PR.
class Event(NamedTuple):
    time: datetime
    change: PRChange
    # Additional details about what changed.
    # For CIStatusChanged, this contains the new state.
    # For Label{Added,Removed}, this contains the name of the label added resp. removed.
    # For LabelsAddedRemoved, this contains two lists of the labels added resp. removed.
    extra: dict

    @staticmethod
    def add_label(time: datetime, name: str):
        return Event(time, PRChange.LabelAdded, {"name": name})

    @staticmethod
    def remove_label(time: datetime, name: str):
        return Event(time, PRChange.LabelRemoved, {"name": name})

    @staticmethod
    def add_remove_labels(time: datetime, added: List[str], removed: List[str]):
        return Event(time, PRChange.LabelAddedRemoved, {"added": added, "removed": removed})

    @staticmethod
    def draft(time: datetime):
        return Event(time, PRChange.MarkedDraft, {})

    @staticmethod
    def undraft(time: datetime):
        return Event(time, PRChange.MarkedReady, {})

    @staticmethod
    def update_ci_status(time: datetime, new: CIStatus):
        return Event(time, PRChange.CIStatusChanged, {"new_state": new})


# Update the current PR state in light of some change.
def update_state(current: PRState, ev: Event) -> PRState:
    #print(f"current state is {current}, incoming event is {ev}")
    if ev.change == PRChange.MarkedDraft:
        return PRState(current.labels, current.ci, True, current.from_fork)
    elif ev.change == PRChange.MarkedReady:
        return PRState(current.labels, current.ci, False, current.from_fork)
    elif ev.change == PRChange.CIStatusChanged:
        return PRState(current.labels, ev.extra["new_state"], current.draft, current.from_fork)
    elif ev.change == PRChange.LabelAdded:
        # Depending on the label added, update the PR status.
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            label_kind = label_categorisation_rules[lname]
            return PRState(current.labels + [label_kind], current.ci, current.draft, current.from_fork)
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
            return PRState(new_labels, current.ci, current.draft, current.from_fork)
        else:
            # Removing an irrelevant label does not change the PR status.
            return current
    elif ev.change == PRChange.LabelAddedRemoved:
        added = ev.extra["added"]
        removed = ev.extra["removed"]
        # Remove any label which is both added and removed, and filter out irrelevant labels.
        both = set(added) & set(removed)
        added = [l for l in added if l in label_categorisation_rules and l not in both]
        removed = [l for l in removed if l in label_categorisation_rules and l not in both]
        # Any remaining labels to be removed should exist.
        new_labels = current.labels[:]
        for r in removed:
            new_labels.remove(label_categorisation_rules[r])
        return PRState(new_labels + [label_categorisation_rules[l] for l in added], current.ci, current.draft, current.from_fork)
    else:
        print(f"unhandled event variant {ev.change}")
        assert False


# Determine the evolution of this PR's state over time, starting from a given state at some time.
# Return a list of pairs (timestamp, s), where this PR moved into state *s* at time *timestamp*.
# The first item corresponds to the PR's creation.
def determine_state_changes(
    creation_time: datetime, initial_state: PRState, events: List[Event]
) -> List[Tuple[datetime, PRState]]:
    result = []
    result.append((creation_time, initial_state))
    curr_state = initial_state
    for event in events:
        new_state = update_state(curr_state, event)
        result.append((event.time, new_state))
        curr_state = new_state
    return result


# Determine the evolution of this PR's status over time.
# Return a list of pairs (timestamp, st), where this PR moved into status *st* at time *timestamp*.
# The first item corresponds to the PR's creation.
def determine_status_changes(
    initial_time: datetime, initial_state: PRState, events: List[Event]
) -> List[Tuple[datetime, PRStatus]]:
    evolution = determine_state_changes(initial_time, initial_state, events)
    #print(f"state changes are {evolution}")
    res = []
    for time, state in evolution:
        res.append((time, determine_PR_status(time, state)))
    return res


########### Overall computation #########


def total_time_in_status(creation_time: datetime, now: datetime, initial_state: PRState, events: List[Event], status: PRStatus) -> relativedelta:
    '''Determine the total amount of time this PR was in a given status,
    from its creation to the current time.'''
    total = relativedelta(days=0)
    evolution_status = determine_status_changes(creation_time, initial_state, events)
    # The PR creation should be the first event in `evolution_status`.
    assert len(evolution_status) == len(events) + 1
    for i in range(len(evolution_status) - 1):
        (old_time, old_status) = evolution_status[i]
        (new_time, _new_status) = evolution_status[i + 1]
        if old_status == status:
            total += new_time - old_time
    (last, last_status) = evolution_status[-1]
    if last_status == status:
        total += now - last
    return total


# Determine the total amount of time this PR was awaiting review.
#
# FUTURE ideas for tweaking this reporting:
#  - ignore short intervals of merge conflicts, say less than a day?
#  - ignore short intervals of CI running (if successful before and after)?
def total_queue_time(creation_time: datetime, now: datetime, initial_state: PRState, events: List[Event]) -> relativedelta:
    return total_time_in_status(creation_time, now, initial_state, events, PRStatus.AwaitingReview)


# Return the total time since this PR's last status change.
def last_status_update(
    creation_time: datetime, now: datetime, created_as_draft: bool, from_fork: bool, events: List[Event]
) -> relativedelta:
    '''Compute the total time since this PR's state changed last.'''
    # We assume the PR was created in passing state without labels
    initial_state = PRState([], CIStatus.Pass, created_as_draft, from_fork)
    # FUTURE: should this ignore short-lived merge conflicts? for now, it does not
    evolution_status = determine_status_changes(creation_time, initial_state, events)
    # The PR creation should be the first event in `evolution_status`.
    assert len(evolution_status) == len(events) + 1
    last : datetime = evolution_status[-1][0]
    return relativedelta(now, last)


# Canonicalise a (potentially historical) label name to its current one.
# Github's events data uses the label names at that time.
def canonicalise_label(name: str) -> str:
    return "awaiting-review-DONT-USE" if name == "awaiting-review" else name


# Parse the detailed information about a given PR and return a pair
# (creation_data, relevant_events) of the PR's creation date (in UTC time)
# and all relevant events which change a PR's state.
def parse_data(data: dict) -> Tuple[datetime, List[Event]]:
    creation_time = parser.isoparse(data["data"]["repository"]["pullRequest"]["createdAt"])
    events = []
    events_data = data["data"]["repository"]["pullRequest"]["timelineItems"]["nodes"]
    known_irrelevant = [
        "ClosedEvent", "ReopenedEvent", "BaseRefChangedEvent", "HeadRefForcePushedEvent", "HeadRefDeletedEvent",
        "PullRequestCommit", "IssueComment", "PullRequestReview", "RenamedTitleEvent", "AssignedEvent", "UnassignedEvent",
        "ReferencedEvent", "CrossReferencedEvent", "MentionedEvent",
        "ReviewRequestedEvent", "ReviewRequestRemovedEvent",
        "SubscribedEvent", "UnsubscribedEvent",
        "CommentDeletedEvent",
    ]
    for event in events_data:
        match event["__typename"]:
            case "LabeledEvent":
                time = parser.isoparse(event["createdAt"])
                name = canonicalise_label(event["label"]["name"])
                events.append(Event.add_label(time, name))
            case "UnlabeledEvent":
                time = parser.isoparse(event["createdAt"])
                name = canonicalise_label(event["label"]["name"])
                events.append(Event.remove_label(time, name))
            case "ReadyForReviewEvent":
                time = parser.isoparse(event["createdAt"])
                events.append(Event.undraft(time))
            case "ConvertToDraftEvent":
                time = parser.isoparse(event["createdAt"])
                events.append(Event.draft(time))
            case other_kind if other_kind not in known_irrelevant:
                print(f"unhandled event kind: {other_kind}")
    return (creation_time, events)


# Determine a rough estimate how long PR 'number' is in its current state,
# and how long it was in its current state overall.
# 'data' is a JSON object containing all known information about a PR.
#
# TODO:
# - parse current draft, CI status and feed this into any other methods which need it!
#   determine_status_changes, for instance, would need such an initial input!
# - assumes CI always passes, i.e. ignores failing or running CI
#   (the *classification* doesn't, but I don't parse CI info yet... that only works
#    for full data, so this would need a "full data" boolean to not yield errors)
def last_real_update(data: dict) -> relativedelta:
    (createdAt, events) = parse_data(data)
    created_as_draft = False # TODO!
    from_fork = False # TODO!
    return last_status_update(createdAt, datetime.now(timezone.utc), created_as_draft, from_fork, events)


# UX for the generated dashboards: expose both total time and current time in the current state
# review time for the queue, "merge"/"delegated" for the stale "XY" dashboard; "merge conflict" for the merge conflict list
# allow filtering by both the "current streak" and the "total time" in this status


######### Some basic unit tests ##########

# Helper methods to reduce boilerplate


def april(n: int) -> datetime:
    return datetime(2024, 4, n, tzinfo=tz.tzutc())


def sep(n: int) -> datetime:
    return datetime(2024, 9, n, tzinfo=tz.tzutc())


# These tests are just some basic smoketests and not exhaustive.
def test_determine_state_changes() -> None:
    def check(events: List[Event], expected: PRState) -> None:
        initial = PRState([], CIStatus.Pass, False, False)
        compute = determine_state_changes(datetime(2024, 7, 15, tzinfo=tz.tzutc()), initial, events)
        actual = compute[-1][1]
        assert expected == actual, f"expected PR state {expected} from events {events}, got {actual}"
    check([], PRState.with_labels_and_ci([], CIStatus.Pass))
    dummy = datetime(2024, 7, 2, tzinfo=tz.tzutc())
    # Drafting or undrafting; changing CI status.
    check([Event.draft(dummy)], PRState.with_labels_ci_draft([], CIStatus.Pass, True))
    check([Event.draft(dummy), Event.undraft(dummy)], PRState.with_labels_ci_draft([], CIStatus.Pass, False))
    # Additional "undraft" or "draft" events are ignored.
    check([Event.undraft(dummy)], PRState.with_labels_ci_draft([], CIStatus.Pass, False))
    check([Event.undraft(dummy), Event.undraft(dummy), Event.draft(dummy)], PRState.with_labels_ci_draft([], CIStatus.Pass, True))
    check([Event.undraft(dummy), Event.draft(dummy), Event.draft(dummy)], PRState.with_labels_ci_draft([], CIStatus.Pass, True))
    # Updating the CI status.
    check([Event.update_ci_status(dummy, CIStatus.Running)], PRState.with_labels_and_ci([], CIStatus.Running))
    check([Event.update_ci_status(dummy, CIStatus.Fail)], PRState.with_labels_and_ci([], CIStatus.Fail))
    check([Event.update_ci_status(dummy, CIStatus.Pass)], PRState.with_labels_and_ci([], CIStatus.Pass))
    check([Event.update_ci_status(dummy, CIStatus.Pass), Event.update_ci_status(dummy, CIStatus.Fail)], PRState.with_labels_and_ci([], CIStatus.Fail))
    check([Event.update_ci_status(dummy, CIStatus.Pass), Event.draft(dummy), Event.update_ci_status(dummy, CIStatus.Running), Event.undraft(dummy)], PRState.with_labels_and_ci([], CIStatus.Running))

    # Adding and removing labels.
    check([Event.add_label(dummy, "WIP")], PRState.with_labels([LabelKind.WIP]))
    check([Event.add_label(dummy, "awaiting-author")], PRState.with_labels([LabelKind.Author]))
    # Non-relevant labels are not recorded here.
    check([Event.add_label(dummy, "t-data")], PRState.with_labels([]))
    check([Event.add_label(dummy, "t-data"), Event.add_label(dummy, "WIP")], PRState.with_labels([LabelKind.WIP]))
    check([Event.add_label(dummy, "t-data"), Event.add_label(dummy, "WIP"), Event.remove_label(dummy, "t-data")], PRState.with_labels([LabelKind.WIP]))
    # Adding two labels.
    check([Event.add_label(dummy, "awaiting-author")], PRState.with_labels([LabelKind.Author]))
    check([Event.add_label(dummy, "awaiting-author"), Event.add_label(dummy, "WIP")], PRState.with_labels([LabelKind.Author, LabelKind.WIP]))
    check([Event.add_label(dummy, "awaiting-author"), Event.remove_label(dummy, "awaiting-author")], PRState.with_labels([]))
    check([Event.add_label(dummy, "awaiting-author"), Event.remove_label(dummy, "awaiting-author"), Event.add_label(dummy, "awaiting-zulip")], PRState.with_labels([LabelKind.Decision]))
    # TODO: better tests for add-remove
    # - equivalent to individual additions; with irrelevant labels; same for removal
    # - adding and removing same label is a no-op
    # - test that intermediate states are - no errors and - no contradictory states
    #   => need to test intermediate ones -> need the full sequence of states to test?
    check([Event.add_remove_labels(dummy, ["WIP"], ["WIP"])], PRState.with_labels([]))


def smoketest() -> None:
    def check_basic(created: datetime, now: datetime, events: List[Event], expected: relativedelta) -> None:
        initial = PRState([], CIStatus.Pass, False, False)
        wait = total_queue_time(created, now, initial, events)
        assert wait == expected, f"basic test failed: expected total time of {expected} in review, obtained {wait} instead"

    # these pass and behave well
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR')], relativedelta(days=0))
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.add_label(sep(6), 'merge-conflict')], relativedelta(days=0))

    # adding and removing a label yields a BUG: all intermediate lists of labels are empty
    # fixed now, wohoo!
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(6), "blocked-by-other-PR")], relativedelta(days=4))
    # the add_label afterwards was and is fine
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(6), "blocked-by-other-PR"), Event.add_label(sep(8), "WIP")], relativedelta(days=2))

    # trying a variant
    check_basic(sep(1), sep(20), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(8), 'blocked-by-other-PR'), Event.add_label(sep(10), 'WIP')], relativedelta(days=2))
    # current failure, minimized
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(8), 'blocked-by-other-PR')], relativedelta(days=2))

    # Doing nothing in April: not ready for review. In September, it is!
    check_basic(april(1), april(3), [], relativedelta(days=0))
    check_basic(sep(1), sep(3), [], relativedelta(days=2))
    # Applying an irrelevant label.
    check_basic(sep(1), sep(5), [Event.add_label(sep(1), "CI")], relativedelta(days=4))
    # Removing it again.
    check_basic(
        sep(1), sep(12),
        [Event.add_label(sep(1), "CI"), Event.remove_label(sep(3), "CI")],
        relativedelta(days=11),
    )

    # After September 8th, this PR is in WIP status -> only seven days in review.
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'CI'), Event.remove_label(sep(3), 'CI'), Event.add_label(sep(8), 'WIP')], relativedelta(days=7))

    # A PR getting blocked.
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.add_label(sep(8), 'easy')], relativedelta(days=0))
    # A PR getting unblocked again.
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(8), 'blocked-by-other-PR')], relativedelta(days=2))

    # xxx Applying two irrelevant labels.
    # then removing one...
    # more complex tests to come!


# TODO: add basic tests for last_status_update, including asserting that it is positive...


if __name__ == '__main__':
    test_determine_state_changes()
    smoketest()
