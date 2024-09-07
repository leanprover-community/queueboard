## Mathlib4 review and triage dashboard

This repository defines a [dashboard](https://jcommelin.github.io/queueboard/index.html) for reviewing and triaging pull requests to the [mathlib repository](github.com/leanprover-community/mathlib4/). `mathlib` receives a steady (and growing) stream of incoming pull requests. This is great, but keeping track of them all is not an easy task. mathlib's maintainers (and reviewers) observe growing pains trying to manage this using github's built-in functionality. Better tools are needed: this is one of them.

**Status**. The code on this page is a *prototype*. The internals or layout may still change quite a bit! That said:
- the overall functionality of this page is useful, so is probably not going away
- several people have reported finding this useful; feel free to try it out!

There are still some rough edges: feedback on them, as well as on useful improvements, is very welcome! You may file an issue, propose a pull request (from a fork, as usual) or approach us on zulip.

**Contact.** The initial design, architecture and infrastructure of this dashboard were created by Johan Commelin (@jcommelin). Michael Rothgang (@grunweg) contributed improvements to the design, added more dashboards and is working on displaying better "last updated" information.
If you have questions or feedback, feel free to contact us on the [leanprover zulip chat](https://leanprover.zulipchat.com), such as in [in the reviewers stream](https://leanprover.zulipchat.com/#narrow/stream/345428-mathlib-reviewers/topic/proof.20of.20concept.20review.20dashboard) or in the `#mathlib` stream.
