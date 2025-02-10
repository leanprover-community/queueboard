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

from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import List, NamedTuple, Tuple

from dateutil import parser, tz
from dateutil.relativedelta import relativedelta

from classify_pr_state import (CIStatus, LabelKind, PRState, PRStatus,
                               determine_PR_status, label_categorisation_rules,
                               label_to_prstatus)
from util import format_delta


class LabelAdded(NamedTuple):
    """A new label got added"""
    name: str


class LabelRemoved(NamedTuple):
    """An existing label got removed"""
    name: str


class LabelAddedRemoved(NamedTuple):
    """A set of labels was added, and some set of labels was removed.
    Note that a given label can be added and removed at the same time."""
    added: List[str]
    removed: List[str]


class CIStatusChanged(NamedTuple):
    """This PR's CI status changed"""
    new_status: CIStatus


class MarkedDraft(NamedTuple):
    """This PR was marked as draft."""
    pass


class MarkedReady(NamedTuple):
    """This PR was marked as ready for review."""
    pass


# Something changed on a PR which we care about:
# - a new label got added or removed
# - the PR was (un)marked draft: omitting this for now
# - the PR status changed (passing or failing to build)
PRChange = LabelAdded | LabelRemoved | LabelAddedRemoved | MarkedDraft | MarkedReady | CIStatusChanged


# Something changed on this PR.
class Event(NamedTuple):
    time: datetime
    change: PRChange

    @staticmethod
    def add_label(time: datetime, name: str):
        return Event(time, LabelAdded(name))

    @staticmethod
    def remove_label(time: datetime, name: str):
        return Event(time, LabelRemoved(name))

    @staticmethod
    def add_remove_labels(time: datetime, added: List[str], removed: List[str]):
        return Event(time, LabelAddedRemoved(added, removed))

    @staticmethod
    def draft(time: datetime):
        return Event(time, MarkedDraft())

    @staticmethod
    def undraft(time: datetime):
        return Event(time, MarkedReady())

    @staticmethod
    def update_ci_status(time: datetime, new: CIStatus):
        return Event(time, CIStatusChanged(new))


# Update the current PR state in light of some change.
def update_state(current: PRState, ev: Event) -> PRState:
    #print(f"current state is {current}, incoming event is {ev}")
    match ev.change:
        case MarkedDraft():
            return PRState(current.labels, current.ci, True, current.from_fork)
        case MarkedReady():
            return PRState(current.labels, current.ci, False, current.from_fork)
        case CIStatusChanged(new_state):
            return PRState(current.labels, new_state, current.draft, current.from_fork)
        case LabelAdded(name):
            # Depending on the label added, update the PR status.
            if name in label_categorisation_rules:
                label_kind = label_categorisation_rules[name]
                return PRState(current.labels + [label_kind], current.ci, current.draft, current.from_fork)
            else:
                # Adding an irrelevant label does not change the PR status.
                if not name.startswith("t-") and name != "CI":
                    pass  # print(f"found irrelevant label: {name}")
                return current
        case LabelRemoved(name):
            if name in label_categorisation_rules:
                # NB: make sure to *copy* current.labels using [:], otherwise that state is also modified!
                new_labels = current.labels[:]
                new_labels.remove(label_categorisation_rules[name])
                return PRState(new_labels, current.ci, current.draft, current.from_fork)
            else:
                # Removing an irrelevant label does not change the PR status.
                return current
        case LabelAddedRemoved(added, removed):
            # Remove any label which is both added and removed, and filter out irrelevant labels.
            both = set(added) & set(removed)
            added = [l for l in added if l in label_categorisation_rules and l not in both]
            removed = [l for l in removed if l in label_categorisation_rules and l not in both]
            # Any remaining labels to be removed should exist.
            new_labels = current.labels[:]
            for r in removed:
                new_labels.remove(label_categorisation_rules[r])
            return PRState(new_labels + [label_categorisation_rules[l] for l in added], current.ci, current.draft, current.from_fork)
        case _:
            print(f"unhandled event: {ev.change}")
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


def total_time_in_status(
    creation_time: datetime, now: datetime, initial_state: PRState, events: List[Event], status: PRStatus
) -> Tuple[Tuple[timedelta, relativedelta], str]:
    '''Determine the total amount of time this PR was in a given status,
    from its creation to the current time.

    Returns a tuple (time, description), where
    - description lists the times in that state in human-readable form, and
    - time is a tuple (td, rd), containing the total time in this state,
      once as a timedelta (i.e. only knowing days, not e.g. months) and
      once as a relativedelta. The former is more useful for comparing time spans,
      the latter provides nicer output for users.'''
    explanation = ""
    total_rd = relativedelta(days=0)
    total_td = timedelta(days=0)
    evolution_status = determine_status_changes(creation_time, initial_state, events)
    # The PR creation should be the first event in `evolution_status`.
    assert len(evolution_status) == len(events) + 1
    for i in range(len(evolution_status) - 1):
        (old_time, old_status) = evolution_status[i]
        (new_time, _new_status) = evolution_status[i + 1]
        if old_status == status:
            explanation += f"from {old_time} to {new_time} ({format_delta(relativedelta(new_time, old_time))})\n"
            total_rd += new_time - old_time
            total_td += new_time - old_time
    (last, last_status) = evolution_status[-1]
    if last_status == status:
        total_rd += now - last
        total_td += now - last
        explanation += f"since {last} ({format_delta(relativedelta(now, last))})\n"
    return ((total_td, total_rd), explanation.rstrip().replace("+00:00", ""))


class Metadata(NamedTuple):
    """All necessary input data for analysing a PR's state evolution: its creation time, initial state
    and all relevant changes to its state over time."""
    created_at: datetime
    events: List[Event]
    created_as_draft: bool
    from_fork: bool


# Determine the total amount of time this PR was awaiting review.
#
# FUTURE ideas for tweaking this reporting:
#  - ignore short intervals of merge conflicts, say less than a day?
#  - ignore short intervals of CI running (if successful before and after)?
def total_queue_time_inner(now: datetime, metadata: Metadata) -> Tuple[Tuple[timedelta, relativedelta], str]:
    # We assume the PR was created in passing state without labels.
    initial_state = PRState([], CIStatus.Pass, metadata.created_as_draft, metadata.from_fork)
    return total_time_in_status(metadata.created_at, now, initial_state, metadata.events, PRStatus.AwaitingReview)


# Determine the first point in time a PR was on the review queue; return None if this never happened so far.
def first_on_queue(metadata) -> datetime | None:
    # We assume the PR was created in passing state without labels.
    initial_state = PRState([], CIStatus.Pass, metadata.created_as_draft, metadata.from_fork)
    evolution_status = determine_status_changes(metadata.created_at, initial_state, metadata.events)
    # The first state in |evolution_status| is the initial state.
    # If a label was added "immediately", we do not count this state.
    if len(evolution_status) > 1:
        if evolution_status[0][0] == evolution_status[1][0]:
            _ = evolution_status.pop(0)
    for (time, status) in evolution_status:
        if status == PRStatus.AwaitingReview:
            return time
    return None


# Return the total time since this PR's last status change,
# as a tuple (absolute time, time since now).
def last_status_update(now: datetime, metadata: Metadata) -> Tuple[datetime, relativedelta, PRStatus]:
    '''Compute the total time since this PR's state changed last.'''
    # We assume the PR was created in passing state without labels.
    initial_state = PRState([], CIStatus.Pass, metadata.created_as_draft, metadata.from_fork)
    # FUTURE: should this ignore short-lived merge conflicts? for now, it does not
    evolution_status = determine_status_changes(metadata.created_at, initial_state, metadata.events)
    # The PR creation should be the first event in `evolution_status`.
    assert len(evolution_status) == len(metadata.events) + 1
    last : datetime = evolution_status[-1][0]
    return (last, relativedelta(now, last), evolution_status[-1][1])


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
        "ReviewRequestedEvent", "ReviewRequestRemovedEvent", "ReviewDismissedEvent",
        "ConnectedEvent", "DisconnectedEvent",  # no idea what these are used for
        "SubscribedEvent", "UnsubscribedEvent",
        "CommentDeletedEvent",
        "MergedEvent", "BaseRefForcePushedEvent", "MarkedAsDuplicateEvent",
        "PullRequestRevisionMarker", "BaseRefDeletedEvent", "HeadRefRestoredEvent",
        "AddedToMergeQueueEvent", "RemovedFromMergeQueueEvent",
    ]
    for event in events_data:
        match event.get("__typename"):
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


def _process_data(data: dict) -> Metadata:
    (createdAt, events) = parse_data(data)
    inner_data = data["data"]["repository"]["pullRequest"]

    # A PR started as draft iff the number of events toggling its state "differs" from the final
    # draft status, e.g. five toggles and not-draft means the PR started as draft.
    # Logically, this is the XOR of the values "draft was toggled overall" and "final state is draft".
    # This is truthy iff the draft state was toggled an odd number of times.
    draft_toggled_overall = len([e for e in events if e.change in [MarkedDraft, MarkedReady]]) % 2
    final_draft_state = inner_data["isDraft"]
    created_as_draft = draft_toggled_overall ^ final_draft_state

    from_fork = inner_data["headRepositoryOwner"]["login"] != "leanprover-community"
    return Metadata(createdAt, events, created_as_draft, from_fork)


# Determine a rough estimate how long PR 'number' is in its current state,
# and how long it was in its current state overall.
# 'data' is a JSON object containing all known information about a PR.
#
# TODO: this algorithm pretends CI always passes, i.e. ignores failing or running CI
#   (the *classification* doesn't, but I don't parse CI info yet... that only works
#    for full data, so this would need a "full data" boolean to not yield errors)
def last_real_update(data: dict) -> Tuple[datetime, relativedelta, PRStatus]:
    metadata = _process_data(data)
    return last_status_update(datetime.now(timezone.utc), metadata)


def total_queue_time(data: dict) -> Tuple[Tuple[timedelta, relativedelta], str]:
    metadata = _process_data(data)
    return total_queue_time_inner(datetime.now(timezone.utc), metadata)


def first_time_on_queue(data: dict) -> datetime | None:
    metadata = _process_data(data)
    return first_on_queue(metadata)

######### Some basic unit tests ##########

# Helper methods to reduce boilerplate


def april(n: int) -> datetime:
    return datetime(2024, 4, n, tzinfo=tz.tzutc())
def june(n: int) -> datetime:
    return datetime(2024, 6, n, tzinfo=tz.tzutc())
def july(n: int) -> datetime:
    return datetime(2024, 7, n, tzinfo=tz.tzutc())
def aug(n: int) -> datetime:
    return datetime(2024, 8, n, tzinfo=tz.tzutc())
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


def test_total_queue_time() -> None:
    def check_basic(created: datetime, now: datetime, events: List[Event], expected: relativedelta) -> None:
        ((_, wait), _) = total_queue_time_inner(now, Metadata(created, events, False, False))
        assert wait == expected, f"basic test failed: expected total time of {expected} in review, obtained {wait} instead"
    def check_with_initial(now: datetime, state: Metadata, expected: relativedelta) -> None:
        ((_, wait), _) = total_queue_time_inner(now, state)
        assert wait == expected, f"test failed: expected total time of {expected} in review, obtained {wait} instead"

    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR')], relativedelta(days=0))
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.add_label(sep(6), 'merge-conflict')], relativedelta(days=0))

    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(6), "blocked-by-other-PR")], relativedelta(days=4))
    check_basic(sep(1), sep(10), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(6), "blocked-by-other-PR"), Event.add_label(sep(8), "WIP")], relativedelta(days=2))

    check_basic(sep(1), sep(20), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.remove_label(sep(8), 'blocked-by-other-PR'), Event.add_label(sep(10), 'WIP')], relativedelta(days=2))
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

    # Apply two irrelevant labels, then removing one.
    check_basic(sep(1), sep(20), [Event.add_label(sep(1), 'blocked-by-other-PR'), Event.add_label(sep(3), 'new-contributor'), Event.add_label(sep(12), 'WIP'), Event.add_label(sep(14), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(18), 'blocked-by-other-PR')], relativedelta(days=0))
    # Still WIP in the end; TODO also test below!
    check_basic(sep(1), sep(20), [Event.add_label(sep(10), 'blocked-by-other-PR'), Event.add_label(sep(13), 'new-contributor'), Event.add_label(sep(14), 'WIP'), Event.add_label(sep(16), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(18), 'blocked-by-other-PR')], relativedelta(days=9))
    # Waiting for review in the end.
    check_basic(sep(1), sep(20), [Event.add_label(sep(10), 'blocked-by-other-PR'), Event.add_label(sep(13), 'new-contributor'), Event.add_label(sep(14), 'WIP'), Event.add_label(sep(16), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(18), 'blocked-by-other-PR'), Event.remove_label(sep(19), 'WIP')], relativedelta(days=10))

    # Some more complex tests, adapted from real PRs.
    # Adapted from PR 16666: created in draft state.
    events = [Event.add_label(sep(10), 't-meta'), Event.undraft(sep(10)), Event.add_label(sep(29), 'ready-to-merge')]
    check_basic(sep(1), sep(30), events, relativedelta(days=28))
    check_with_initial(sep(30), Metadata(sep(1), events, True, False), relativedelta(days=19))

    # Minimised from PR 14269
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
    ]
    check_with_initial(sep(30), Metadata(june(28), events, False, False), relativedelta(days=2))

    # Subtle detail: the awaiting-review flag is not removed on July 9th (for these data),
    # so a new assessment of the state only happens at the later label changes.
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
        Event.add_label(july(1), 'awaiting-review-DONT-USE'), Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'), Event.remove_label(july(2), 'awaiting-author'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(july(13), 'WIP'),
        # is now without essential labels -> reviewable
        Event.add_label(july(13), 'help-wanted'), Event.add_label(aug(8), 'awaiting-author'), # waiting for help
        Event.add_label(aug(15), 't-number-theory'), Event.remove_label(sep(3), 'awaiting-author'), # help-wanted
        # two days awaiting review: September 20 to 22
        Event.remove_label(sep(20), 'help-wanted'), Event.add_label(sep(22), 'awaiting-author'),
    ]
    check_with_initial(sep(25), Metadata(june(29), events, False, False), relativedelta(days=4))

    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
        Event.add_label(july(1), 'awaiting-review-DONT-USE'), Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'), Event.remove_label(july(2), 'awaiting-author'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(july(13), 'WIP'),
        # is now without essential labels -> reviewable
        Event.add_label(july(13), 'help-wanted'), Event.add_label(aug(8), 'awaiting-author'), # waiting for help
        Event.add_label(aug(15), 't-number-theory'), Event.remove_label(sep(3), 'awaiting-author'), # help-wanted
        # two days awaiting review: September 20 to 22
        Event.remove_label(sep(20), 'help-wanted'), Event.add_label(sep(22), 'awaiting-author'), Event.remove_label(sep(23), 'awaiting-author')
        # on the queue now
    ]
    check_with_initial(sep(27), Metadata(june(29), events, False, False), relativedelta(days=8))

    events = [Event.draft(sep(3)), Event.add_label(sep(10), 't-meta'), Event.undraft(sep(10)), Event.draft(sep(15)), Event.add_label(sep(29), 'ready-to-merge')]
    # total review time windows: sep 1-3, sep 10-15: 7 days
    check_with_initial(sep(30), Metadata(sep(1), events, False, False), relativedelta(days=7))


# Some basic tests for last_status_update and first time on the queue.
def test_last_status_update():
    def check_with_initial(now: datetime, state: Metadata, expected: Tuple[datetime, relativedelta, PRStatus]) -> None:
        (absolute, relative, last_status) = last_status_update(now, state)
        assert absolute == expected[0], f"basic test failed: expected last update on {expected[0]} in review, obtained {absolute} instead"
        assert relative == expected[1], f"basic test failed: expected last update on {expected[1]} in review, obtained {relative} instead"
        assert last_status == expected[2], f"expected last PR status of {expected[2]}, obtained {last_status} instead"
    def check_basic(created: datetime, now: datetime, events: List[Event], expected: Tuple[datetime, relativedelta, PRStatus]) -> None:
        check_with_initial(now, Metadata(created, events, False, False), expected)
    def check_first(metadata: Metadata, expected: datetime) -> None:
        actual = first_on_queue(metadata)
        assert actual == expected, f"expect first time on the queue of {expected}, obtained {actual} instead"
    def check_first_basic(created: datetime, events: List[Event], expected: datetime) -> None:
        check_first(Metadata(created, events, False, False), expected)

    events = [
        Event.add_label(sep(10), 'blocked-by-other-PR'), Event.add_label(sep(13), 'new-contributor'), Event.add_label(sep(14), 'WIP'), Event.add_label(sep(16), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(18), 'AIMS')
    ]
    check_basic(sep(1), sep(20), events, (sep(18), relativedelta(days=2), PRStatus.Blocked))
    # The PR is created and stays without labels for 9 days.
    check_first_basic(sep(1), events, sep(1))
    # Now, it is created and labelled at the same time: we do not regard the initial "0 seconds" as ready for review.
    check_first_basic(sep(10), events, None)

    events = [
        Event.add_label(sep(10), 'blocked-by-other-PR'), Event.add_label(sep(13), 'new-contributor'), Event.add_label(sep(14), 'WIP'), Event.add_label(sep(16), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(19), 'blocked-by-other-PR')
    ]
    check_basic(sep(1), sep(22), events, (sep(19), relativedelta(days=3), PRStatus.NotReady))
    check_first_basic(sep(1), events, sep(1))
    check_first_basic(sep(10), events, None)
    events = [
        Event.add_label(sep(10), 'blocked-by-other-PR'), Event.add_label(sep(13), 'new-contributor'), Event.add_label(sep(14), 'WIP'), Event.add_label(sep(16), 'AIMS'), Event.remove_label(sep(16), 'new-contributor'), Event.remove_label(sep(19), 'blocked-by-other-PR'), Event.remove_label(sep(20), 'WIP')
    ]
    check_basic(sep(1), sep(24), events, (sep(20), relativedelta(days=4), PRStatus.AwaitingReview))
    check_first_basic(sep(10), events, sep(20))

    # Adapted from PR 16666: created in draft state.
    events = [Event.add_label(sep(10), 't-meta'), Event.undraft(sep(11)), Event.add_label(sep(25), 'ready-to-merge')]
    check_basic(sep(1), sep(30), events, (sep(25), relativedelta(days=5), PRStatus.AwaitingBors))
    check_with_initial(sep(28), Metadata(sep(1), events, True, False), (sep(25), relativedelta(days=3), PRStatus.AwaitingBors))
    check_first_basic(sep(9), events, sep(9))

    events = [Event.draft(sep(3)), Event.add_label(sep(10), 't-meta'), Event.undraft(sep(10)), Event.draft(sep(15)), Event.add_label(sep(29), 'WIP-to-merge')]
    check_with_initial(sep(30), Metadata(sep(1), events, False, False), (sep(29), relativedelta(days=1), PRStatus.NotReady))
    check_first_basic(sep(3), events, sep(10))
    # Minimised from PR 14269
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
    ]
    check_with_initial(sep(30), Metadata(june(28), events, False, False), (july(1), relativedelta(months=2, days=29), PRStatus.AwaitingAuthor))
    check_first_basic(june(29), events, june(29))
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_remove_labels(july(1), ['awaiting-author'], ["awaiting-author"]),
    ]
    check_with_initial(sep(30), Metadata(june(28), events, False, False), (july(1), relativedelta(months=2, days=29), PRStatus.AwaitingAuthor))
    check_first_basic(june(28), events, june(29))

    # This one illustrates a subtle change of labels: removing the label on July 13 means this is awaiting review.
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
        Event.add_label(july(1), 'awaiting-review-DONT-USE'), Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'), Event.remove_label(july(2), 'awaiting-author'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(july(13), 'WIP'),
    ]
    check_with_initial(aug(30), Metadata(june(28), events, False, False), (july(13), relativedelta(months=1, days=17), PRStatus.AwaitingReview))
    check_first_basic(june(28), events, june(29))

    # This one illustrates a subtle change of labels: removing the label on July 13 means this is awaiting review.
    # Doing so a month later would have triggered my algorithm later.
    # (In practice, all review labels were removed on July 9th, so this is purely hypothetical.)
    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(aug(13), 'WIP'),
    ]
    check_with_initial(aug(30), Metadata(june(27), events, False, False), (aug(13), relativedelta(days=17), PRStatus.AwaitingReview))
    check_first_basic(june(27), events, june(29))

    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'),
        Event.remove_label(july(1), 'awaiting-author'),
        Event.add_label(july(1), 'awaiting-review-DONT-USE'), Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'), Event.remove_label(july(2), 'awaiting-author'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(july(13), 'WIP'),
        Event.add_label(july(13), 'help-wanted'), Event.add_label(aug(8), 'awaiting-author'),
    ]
    check_with_initial(aug(30), Metadata(june(28), events, False, False), (aug(8), relativedelta(days=22), PRStatus.HelpWanted))
    check_first_basic(june(28), events, june(29))

    events = [
        Event.add_label(june(29), 'awaiting-review-DONT-USE'),
        Event.add_label(june(29), 'new-contributor'),
        Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-review-DONT-USE'), Event.remove_label(july(1), 'awaiting-review-DONT-USE'),
        Event.add_label(july(1), 'awaiting-author'), Event.remove_label(july(2), 'awaiting-author'),
        Event.add_label(july(2), 'WIP'), Event.remove_label(july(13), 'WIP'),
        Event.add_label(july(13), 'help-wanted'), Event.add_label(aug(8), 'awaiting-author'),
        Event.add_label(aug(15), 't-number-theory'), Event.remove_label(sep(3), 'awaiting-author'),
        Event.remove_label(sep(20), 'help-wanted'), Event.add_label(sep(22), 'awaiting-author'), Event.remove_label(sep(23), 'awaiting-author')
    ]
    check_with_initial(sep(30), Metadata(june(28), events, False, False), (sep(23), relativedelta(days=7), PRStatus.AwaitingReview))
    check_first_basic(june(28), events, june(29))


if __name__ == '__main__':
    test_determine_state_changes()
    test_total_queue_time()
    test_last_status_update()
