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
class PRState(Enum):
    # This PR is marked as work in progress.
    # FUTURE: if this PR is marked as draft or CI fails (or just: fails initially?), also mark as such.
    NotReady = auto()
    # This PR is blocked on another PR, to mathlib, core or batteries.
    Blocked = auto()
    AwaitingReview = auto()
    # Review comments to process: different from "not ready"
    AwaitingAuthor = auto()
    # This PR is blocked on a decision: the awaiting-zulip label signifies this.
    # FIXME: actually assign this label; for now, we do not do so.
    AwaitingDecision = auto()
    # This PR has a merge conflict and is ready, not blocked on another PR,
    # not awaiting author action and and otherwise awaiting review.
    # (Put differently, "blocked", "not ready" or "awaiting-author" take precedence over a merge conflict.
    # FIXME: not sure how to analyse this later!! -> move fixme there!
    MergeConflict = auto()

    # This PR was delegated to the user.
    # FIXME: for now, we ignore this category and treat it the same as awaiting-author.
    Delegated = auto()
    # Ready-to-merge or auto-merge-after-CI. Can become stale if CI fails/multiple retries etc.
    AwaitingBors = auto()
    # FIXME: do we actually need this category?
    Closed = auto()


# Something changed on a PR which we care about:
# - a new label got added or removed
# - the PR was (un)marked draft: omitting this for now
# - the PR status changed (passing or failing to build)
#
# XXX: the most elegant design would be using sum types, i.e. encoding the details of that change
# as part of each variant's data. That is not possible in Python...
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
    # For Label{Added,Removed}, this will contain the name of all label(s) added/resp removed.
    extra : dict

# XXX: when a label gets renamed, do all occurences of that label get renamed? yes, they do.
# so unless we are scraping data from github and patching things together, we need not worry about this

# The different kinds of PR labels we care about.
# We usually do not care about the precise label names, but just their function.
class LabelKind(Enum):
    Review = auto() # awaiting-review
    Author = auto() # awaiting-author
    MergeConflict = auto() # merge-conflict
    Blocked = auto() # blocked-on-other-PR, etc.
    Decision = auto() # awaiting-zulip
    Delegated = auto() # delegated
    Bors = auto() # ready-to-merge or auto-merge-after-CI
    Other = auto() # any other label, such as t-something (but also "easy", "bug" and a few more)

# Map a label name (as a string) to a tuple of LabelKind, a boolean and a new PR state.
# If true, assert that the previous state was different, as a sanity check.
label_categorisation_rules = {
    'awaiting-review' : LabelKind.AwaitingReview,
    'awaiting-author' : LabelKind.AwaitingAuthor,
    'blocked-on-other-PR' : LabelKind.Blocked,
    'merge-conflict' : LabelKind.MergeConflict,
    'awaiting-zulip' : LabelKind.Decision,
    'delegated' : LabelKind.Delegated,
    'ready-to-merge' : LabelKind.Bors,
}
label_categorisation_rules['blocked-on-batt-PR'] = label_categorisation_rules['blocked-on-other-PR']
label_categorisation_rules['blocked-on-core-PR'] = label_categorisation_rules['blocked-on-other-PR']
label_categorisation_rules['auto-merge-after-CI'] = label_categorisation_rules['ready-to-merge']

def label_to_prstate(label : LabelKind) -> PRState:
    {
        LabelKind.Review: PRState.AwaitingReview,
        LabelKind.Author: PRState.AwaitingAuthor,
        LabelKind.Blocked: PRState.Blocked,
        LabelKind.MergeConflict: PRState.MergeConflict,
        LabelKind.Decision: PRState.AwaitingDecision,
        LabelKind.Delegated: PRState.Delegated,
        LabelKind.Bors: PRState.AwaitingBors,
    }[label]

# XXX: the awaiting-review label is just added for historical purposes.
# FIXME: do I need to rename that to match github?

# Update the current state of this PR in light of some activity.
# current_label describes all kinds of labels this PR currently has.
# Return the new labels and PR state.
def update_state(current : PRState, current_labels : List[LabelKind], ev : Event) -> tuple[List[LabelKind], PRState]:
    # Fixme: we ignore these changes for now
    if ev.change in [PRChange.CIStatusChanged, PRChange.ToggleDraftStatus]:
        current
    elif ev.change == PRChange.LabelAdded:
        # Depending on the label added, update the PR state.
        lname = ev.extra["name"]
        if lname in label_categorisation_rules:
            label_kind = label_categorisation_rules[lname]
            new_state = label_to_prstate(label_kind)
            if new_state != [PRState.Blocked, PRState.AwaitingBors]:
                assert current != new_state
            return (current_labels + [label_kind], new_state)
        else:
            # Adding an irrelevant label does not change the PR state.
            if not lname.startswith("t-"):
                print(f'found another label: {lname}')
            return (current_labels, current)
    elif ev.change == PRChange.LabelRemoved:
        lname = ev.extra["name"]
        new_labels = None
        if lname in label_categorisation_rules:
            (label_kind, _) = label_categorisation_rules[lname]
            new_labels = current_labels.remove(label_kind)
            new_state = current

            # Determine the PR state from the current set of labels.
            # Labels can be contradictory, and their priority orders need not be transitive.
            # We start with some approximation here, and hope for the best.
            # Fixme: try all combinations exhaustively to check if this errors??

            # Validate: should I deduplicate the kinds, somewhere?? No!!
            if new_labels == []:
                new_state = PRState.AwaitingReview # default
            elif len(new_labels) == 1:
                new_state = label_to_prstate[new_labels[0]]
            else:
                # Sometimes, labels can be contradictory...; we document our decisions here.

                # merge conflict takes priority over bors, but bors over all other kinds
                #
                # blocked and decision take priority over merge conflict,
                # but merge conflict takes priority over awaiting-review/author
                #
                # blocked takes priority over merge conflict, awaiting author/review/decision,
                # also over bors? sure, also over bors, why not. (but could double-check!)
                #
                # delegated never takes priority

                # definitely contradictory: any two of awaiting-{author,review,decision}
                # TODO: implement this (e.g., compute a "min" of all kinds, with the algorithm above)
                print("two label kinds, that is confusing; omitted for now")
            return (new_labels, new_state)
        else:
            # Removing an irrelevant label does not change the PR state.
            return (current_labels, current)
    else:
        print(f"unhandled variant {ev.change}")
        assert False

