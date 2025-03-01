## Frequently asked questions about the PR state classification

**Question.** Why are pull requests opened from a fork of mathlib (as opposed to a branch) classified separately?
**Answer.** Being opened from a fork means mathlib's CI cannot run normally (because of the caching set-up, for example), hence the PR will never be merged as-is (and there is no complete information on its CI status). Pull requests opened from a fork should be re-opened from the main branch: hence, merely reporting on the existence of such PRs is sufficient for our purposes, and avoids misleading answers.

**Question.** Isn't `awaiting-zulip` and `awaiting-review` a contradiction?
**Answer.** This algorithm considers `awaiting-zulip` are more refined version of "waiting for review": if both are present, a PR's state switches to "waiting on zulip". In practice, since there's no `awaiting-review` label in use any more, this just means `awaiting-zulip` switches a PR's state from ready for review to waiting on a zulip decision.

**Question.** Isn't `awaiting-author` and `awaiting-zulip` a contradictory combination?
**Answer.** This was discussed [on zulip](XXX LINK): the answer is no, as these signal different things. The former signals the author has changes to make (even if reception on zulip is positive); the latter indicates a decision needs to be reached. `awaiting-zulip` is considered the higher priority label.

**Question.** How is passing or failing CI taken into account?
**Answer.** This information is taken into account now!
To be on the review queue, a PR must pass mathlib's CI. Otherwise, failing CI is generally interpreted the same as a `WIP` label: a PR is not yet fully ready for review. (`WIP` PRs can benefit from outside comments, but they are not ready for *full review*.)

**Question.** How about running CI?
**Answer.** Ah, you mean: will CI in progress kick a PR out of review queue? Yes, temporarily it does --- this is considered a better trade-off than listing PRs as reviewable which will fail CI very soon. (Adding another dashboard just for PRs which would be on the queue if just CI passed is possible. Reach out if you think that would be useful!)
Will that interfere with computing the total time looking for review? No, it will not: in hindsight, all CI data for all commits (where CI ran) is present. "Running" is only a transient state present for recent CI runs.
