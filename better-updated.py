'''
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


'''

from typing import List, NamedTuple
from datetime import datetime
from enum import Enum, auto, unique


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
    '''PR labels are contradictory: we cannot determine easily what this PR's status is'''
    Contradictory = auto()


# Something changed on a PR which we care about:
# - a new label got added or removed
# - the PR was (un)marked draft: omitting this for now
# - the PR status changed (passing or failing to build)
#
# The most elegant design would be using sum types, i.e. encoding the data for
# each variant directly within the enum.
# As Python does not have these, we use a dictionary of extra data.
class PRChange(Enum):
    '''A new label got added'''
    LabelAdded = auto()
    '''An existing label got removed'''
    LabelRemoved = auto()
    '''This PR's draft status changed'''
    # FIXME: we ignore this for now
    ToggleDraftStatus = auto()
    '''This's PR's CI state changed'''
    # FIXME: we ignore this for now
    CIStatusChanged = auto()

# XXX: does github produce events like "labels xyz got added and wpq got removed"?
# If so, need to process these separately or something... we will see!
# For now, pretend these are separate events.

# Something changed on this PR.
class Event(NamedTuple):
    time : datetime
    change : PRChange
    # Additional details about what changed.
    # For ToggleDraftStatus and CIStatusChanged, this will be empty for now.
    # For Label{Added,Removed}, this will contain the name of all label(s) added/respectively removed.
    extra : dict

# NB. Make sure this mapping reflects the *current* label names on github.
# When a label gets renamed, all occurrences are renamed to match, including
# historical ones --- so we need not worry about this.

# The different kinds of PR labels we care about.
# We usually do not care about the precise label names, but just their function.
class LabelKind(Enum):
    WIP = auto() # WIP
    '''This PR is ready for review: this label is only added for historical purposes, as mathlib does not use this label any more'''
    Review = auto()
    Author = auto() # awaiting-author
    MergeConflict = auto() # merge-conflict
    Blocked = auto() # blocked-on-other-PR, etc.
    Decision = auto() # awaiting-zulip
    Delegated = auto() # delegated
    Bors = auto() # ready-to-merge or auto-merge-after-CI
    Other = auto() # any other label, such as t-something (but also "easy", "bug" and a few more)

class CIStatus(Enum):
    Pass = auto()
    Fail = auto()
    Running = auto()

# All relevant state of a PR at each point in time.
class PRState(NamedTuple):
    labels : List[LabelKind]
    ci: CIStatus
    draft : bool


# Map a label name (as a string) to a `LabelKind`.
label_categorisation_rules : dict[str, LabelKind] = {
    'WIP' : LabelKind.WIP,
    'awaiting-review-DONT-USE' : LabelKind.Review,
    'awaiting-author' : LabelKind.Author,
    'blocked-on-other-PR' : LabelKind.Blocked,
    'merge-conflict' : LabelKind.MergeConflict,
    'awaiting-zulip' : LabelKind.Decision,
    'delegated' : LabelKind.Delegated,
    'ready-to-merge' : LabelKind.Bors,
}
label_categorisation_rules['blocked-on-batt-PR'] = label_categorisation_rules['blocked-on-other-PR']
label_categorisation_rules['blocked-on-core-PR'] = label_categorisation_rules['blocked-on-other-PR']
label_categorisation_rules['auto-merge-after-CI'] = label_categorisation_rules['ready-to-merge']

def label_to_prstatus(label : LabelKind) -> PRStatus:
    {
        LabelKind.WIP: PRStatus.NotReady,
        LabelKind.Review: PRStatus.AwaitingReview,
        LabelKind.Author: PRStatus.AwaitingAuthor,
        LabelKind.Blocked: PRStatus.Blocked,
        LabelKind.MergeConflict: PRStatus.MergeConflict,
        LabelKind.Decision: PRStatus.AwaitingDecision,
        LabelKind.Delegated: PRStatus.Delegated,
        LabelKind.Bors: PRStatus.AwaitingBors,
    }[label]


# Determine a PR's status just from its labels.
# Assumes that "insignificant labels" have been filtered out.
# FUTURE: also take the PRs CI status and draft status into account.
def determine_PR_status(labels : List[LabelKind]) -> PRStatus:
    # Labels can be contradictory (so we need to recognise this).
    # Also note that their priority orders are not transitive!
    # TODO: is this actually a problem for our algorithm?
    # NB. A PR *can* legitimately have *two* labels of a blocked kind, for example,
    # so we *do not* want to deduplicate the kinds here.
    if labels == []:
        return PRStatus.AwaitingReview # default
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
        if len([l for l in labels if l in [LabelKind.Author, LabelKind.Review]]):
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory
        # as is being ready-for-merge and blocked.
        if len([l for l in labels if l in [LabelKind.Bors, LabelKind.Blocked]]):
            print(f"contradictory label kinds: {labels}")
            return PRStatus.Contradictory

        # Any item is equal it itself.
        # Store all pairs (kind, kind2) where 'kind' has lower prior
        # than 'kind2' for determining this PR's status.
        lower_than : List[LabelKind, LabelKind] = [
            # "Blocked" tages priority over most other labels.
            (LabelKind.Author, LabelKind.Blocked),
            (LabelKind.Review, LabelKind.Blocked),
            (LabelKind.Decision, LabelKind.Blocked),
            (LabelKind.MergeConflict, LabelKind.Blocked),
            (LabelKind.WIP, LabelKind.Blocked),
            # A PR should be **not** be marked ready-for-merge and b
            # Weird combination, but could make sense.
            (LabelKind.Delegated, LabelKind.Blocked),

            # A merge conflict takes priority over waiting on author
            (LabelKind.Author, LabelKind.MergeConflict),
            (LabelKind.Review, LabelKind.MergeConflict),
            (LabelKind.Delegated, LabelKind.MergeConflict),
            (LabelKind.Bors, LabelKind.MergeConflict),
            # "Waiting for decision" takes priority over a merge con
            # as does "work in progress".
            # NB. This makes our relation non-transitive, as it is r
            # by definition, but satisfies WIP < Author > Bors > Mer
            # We *can* deal with that, though.
            (LabelKind.MergeConflict, LabelKind.Decision),
            (LabelKind.MergeConflict, LabelKind.WIP),

            # "Waiting for a decision" contradicts the remaining lab

            # Sent to bors takes priority over awaiting review, auth
            # Bors and WIP are contradictory and excluded above.
            # FIXME: In practice, these combinations can occur with
            # in which case this labelling should be reversed. Revis
            (LabelKind.Author, LabelKind.Bors),
            (LabelKind.Review, LabelKind.Bors),
            (LabelKind.Bors, LabelKind.Delegated),

            # Waiting for review and delegated *can* make sense, if
            # as can 'WIP' and delegated.
            (LabelKind.Delegated, LabelKind.Review),
            (LabelKind.Review, LabelKind.WIP),
            (LabelKind.WIP, LabelKind.Author),
            (LabelKind.Delegated, LabelKind.Author),
            # Awaiting review and author is contradictory, as is WIP
        ]
        # Should have 8 choose 2 pairs; 9 of them are excluded above
        assert len(lower_than) + 9 == 28

        # TODO: implement the final decision: compute a min of all k
        print("two label kinds, that is confusing; omitted for now")
        return PRStatus.Closed # TODO, placeholder!


def test_determine_status():
    def check(labels: List[LabelKind], expected : PRStatus):
        actual = determine_PR_status(labels)
        assert expected == actual, f"expected PR status {expected} from labels {labels}, got {actual}"
    # All label kinds we distinguish.
    ALL = LabelKind._member_map_.values()
    # For each combination of labels, the resulting PR status is either contradictory
    # or the status associated to some label.
    # The order of adding labels does not matter.
    check([], PRStatus.AwaitingReview)
    for a in ALL:
        check([a], label_to_prstatus(a))
        for b in ALL:
            actual = determine_PR_status([a, b])
            assert actual in [label_to_prstatus(a), label_to_prstatus(b), PRStatus.Contradictory]
            check([b, a], actual)
            for c in ALL:
                # Adding further labels to some contradictory status remains contradictory.
                actual = determine_PR_status([a, b, c])
                if determine_PR_status([a, b]) == PRStatus.Contradictory:
                    check([a, b, c], PRStatus.Contradictory)
                assert actual in [label_to_prstatus(a), label_to_prstatus(b), label_to_prstatus(c), PRStatus.Contradictory]
                check([a, c, b], actual)
                check([b, a, c], actual)
                check([b, c, a], actual)
                check([c, a, b], actual)
                check([c, b, a], actual)
    # One specific sanity check, which fails in the previous implementation.
    check([LabelKind.Blocked, LabelKind.Review], PRStatus.Blocked)
    check([LabelKind.Review, LabelKind.Blocked], PRStatus.Blocked)

test_determine_status()


# Update the current PR state in light of some change.
def update_state(current : PRState, ev : Event) -> PRState:
    if ev.change == PRChange.ToggleDraftStatus:
        return PRState(current.labels, current.ci, not current.draft.toggle)
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
            if not lname.startswith("t-") and lname != 'CI':
                print(f'found another irrelevant label: {lname}')
            return current
    elif ev.change == PRChange.LabelRemoved:
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            (label_kind, _) = label_categorisation_rules[lname]
            return PRState(current.labels.remove(label_kind), current.ci, current.draft)
        else:
            # Removing an irrelevant label does not change the PR status.
            return current
    else:
        print(f"unhandled event variant {ev.change}")
        assert False

# Update the current status of this PR in light of some activity.
# current_label describes all kinds of labels this PR currently has.
# Return the new labels and PR status.
def update_status(current : PRStatus, current_labels : List[LabelKind], ev : Event) -> tuple[List[LabelKind], PRStatus]:
    # FIXME: we ignore these changes for now
    if ev.change in [PRChange.CIStatusChanged, PRChange.ToggleDraftStatus]:
        current
    elif ev.change == PRChange.LabelAdded:
        # Depending on the label added, update the PR status.
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            label_kind = label_categorisation_rules[lname]
            new_status = label_to_prstatus(label_kind)
            if new_status != [PRStatus.Blocked, PRStatus.AwaitingBors]:
                assert new_status != current
            # TODO: this currently fails; use determine_pr_status instead!
            assert new_status == determine_PR_status(current_labels + [label_kind])
            return (current_labels + [label_kind], new_status)
        else:
            # Adding an irrelevant label does not change the PR status.
            if not lname.startswith("t-"):
                print(f'found another label: {lname}')
            return (current_labels, current)
    elif ev.change == PRChange.LabelRemoved:
        lname = ev.extra["name"]
        new_labels = None
        if lname in label_categorisation_rules:
            (label_kind, _) = label_categorisation_rules[lname]
            new_labels = current_labels.remove(label_kind)
            # Determine the PR status from the current set of labels.
            return (new_labels, determine_PR_status(new_labels))
        else:
            # Removing an irrelevant label does not change the PR status.
            return (current_labels, current)
    else:
        print(f"unhandled variant {ev.change}")
        assert False

