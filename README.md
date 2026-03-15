## Mathlib4 review and triage dashboard

This repository contains the workflow used to generate a [dashboard](https://leanprover-community.github.io/queueboard/index.html) for reviewing and triaging pull requests to the [mathlib repository](github.com/leanprover-community/mathlib4/).

**Status.** The data used here is in [queueboard-core](https://github.com/leanprover-community/queueboard-core).
The only code left here consists of the github workflow which needs to remain here so that the resulting web pages can be deployed to the `leanprover-community.github.io//queueboard`.

**Contributing.** Contributions are welcome. If you have questions, feel free to get in touch!
Filing an issue, creating a pull request (from a fork) and providing feedback are all valuable, though most likely you want to refer to the [queueboard-core](https://github.com/leanprover-community/queueboard-core) repo.

**Contact.** The initial design, architecture and infrastructure of this dashboard were created by Johan Commelin (@jcommelin). Michael Rothgang (@grunweg) contributed improvements to the design, added more dashboards and added the analysis of the "last status change" and "total time in review" information.
If you have questions or feedback, feel free to contact us on the [leanprover zulip chat](https://leanprover.zulipchat.com), such as in [the private reviewers stream](https://leanprover.zulipchat.com/#narrow/stream/345428-mathlib-reviewers/topic/proof.20of.20concept.20review.20dashboard) or in the public `#mathlib4` channel.
