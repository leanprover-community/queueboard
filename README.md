## Mathlib4 review and triage dashboard

This repository defines a [dashboard](https://leanprover-community.github.io/queueboard/index.html) for reviewing and triaging pull requests to the [mathlib repository](github.com/leanprover-community/mathlib4/). `mathlib` receives a steady (and growing) stream of incoming pull requests. This is great, but keeping track of them all is not an easy task. mathlib's maintainers (and reviewers) observe growing pains trying to manage this using github's built-in functionality. Better tools are needed: this is one of them.

**Status.** This project is around for a few months now, has been shown to be useful and will most likely stay. Feel free to try it out! Feedback on any issues you find, or changes that would help you, is very welcome.

**Contributing.** Contributions are welcome. If you have questions, feel free to get in touch!
Filing an issue, creating a pull request (from a fork) and providing feedback are all valuable.
There is <a href="https://github.com/leanprover-community/queueboard/issues?q=is%3Aissue%20state%3Aopen%20label%3Ahas-mentoring-instructions">a list of PRs</a> with mentoring instructions.
The [architecture overview](ARCHITECTURE.md) contains for an overall impression of the code base, and [the overall documentation](docs.md) contains some particular details.

**Contact.** The initial design, architecture and infrastructure of this dashboard were created by Johan Commelin (@jcommelin). Michael Rothgang (@grunweg) contributed improvements to the design, added more dashboards and added the analysis of the "last status change" and "total time in review" information.
If you have questions or feedback, feel free to contact us on the [leanprover zulip chat](https://leanprover.zulipchat.com), such as in [the private reviewers stream](https://leanprover.zulipchat.com/#narrow/stream/345428-mathlib-reviewers/topic/proof.20of.20concept.20review.20dashboard) or in the public `#mathlib4` channel.
