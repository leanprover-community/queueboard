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

from typing import NamedTuple
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
class LabelKinds(Enum):
    Review = auto() # awaiting-review
    Author = auto() # awaiting-author
    MergeConflict = auto() # merge-conflict
    Blocked = auto() # blocked-on-other-PR, etc.
    Decision = auto() # awaiting-zulip
    Delegated = auto() # delegated
    Bors = auto() # ready-to-merge or auto-merge-after-CI
    Other = auto() # any other label, such as t-something (but also "easy", "bug" and a few more)



# Update the current state of this PR in light of some activity.
def update_state(current : PRState, ev : Event) -> PRState:
    # Fixme: we ignore these changes for now
    if ev.change in [PRChange.CIStatusChanged, PRChange.ToggleDraftStatus]:
        current
    elif ev.change == PRChange.LabelAdded:
        # Depending on the label added, update the PR state.
        lname = ev.extra["name"]
        if lname == 'awaiting-review':
            assert current != PRState.AwaitingReview  # sanity check
            return PRState.AwaitingReview
        elif lname == 'awaiting-author':
            assert current != PRState.AwaitingAuthor
            return PRState.AwaitingAuthor
        elif lname == "blocked-on-other-PR": # todo others!
            return PRState.Blocked
        elif lname == "merge-conflict":
            assert current != PRState.MergeConflict
            return PRState.MergeConflict
        elif lname == 'awaiting-zulip':
            assert current != PRState.AwaitingDecision
            return PRState.AwaitingDecision
        elif lname == 'delegated':
            assert current != PRState.Delegated
            return PRState.Delegated
        elif lname in ['ready-to-merge', 'auto-merge-after-CI']:
            return PRState.AwaitingBors
        else:
            # Another irrelevant label does not change the PR state.
            if not lname.startswith("t-"):
                print(f'found another label: {lname}')
            return current
    elif ev.change == PRChange.LabelRemoved:
        # TODO: this requires knowing the current set of labels.. my algorithm is stateful!
        pass
    else:
        print(f"unhandled variant {ev.change}")
        assert False

