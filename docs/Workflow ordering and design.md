# Workflow design

This file aims to document why the Github workflows for this project are designed the way they are.
This is incomplete, to be completed!

**Initial choice and history** TODO write! some things to cover
- started with just the webpage (and downloading anew from github)
- then gather_stats was added
- later: aggregate data to publish_webpage; data integrity check; re-downloading automation
Added to the publish_webpage check organically?! (not sure, need to verify!)
- also: conscious refactor to "make this race-free". in October, TODO look up my original intentions + design then!
design flaw: still two workflows pushing to the same branch. cannot be scheduled to not-conflict. tried rebasing; never implemented a retry loop (no good reason, just didn't do it.)


**New design**
avoid push races by design: each workflow only pushes to one branch. cannot have conflicts, this way.
open question: do this speed up pushing again, because this avoids a pull --rebase? will see!
TODO write more here!


**Steps ordering in gather_stats.**
- gather statistics first: is the most important steps of all; also, this may download data that a redownloading step would download again. No need to duplicate work.
- download .json files between the stats gathering and re-downloading: add some delay between these, to avoid hammering github's APIs as much

- check data integrity before redownloading missing PRs: update the list of missing PRs first; no need to download a PR which has been added in the mean-time. For the same reason, gathering stats runs first.
I *could* run this again after re-downloading: there's no immediate need, though. (Before the next data re-downloading, the check is run again. One suffices.)

- update aggregate data files is run *thrice*
The first time after `gather_stats.sh`, so the next steps have up-to-date aggregate files (they need it).
I *could* run this again right after checking the data integrity step. (The step updates the *.txt files, but also removes broken data files --- hence the aggregate data should be updated again.) However, it suffices to run it once in the end, as the re-downloading step doesn't use the aggregate file.
A final run is performed after re-downloading all data. In the end, all aggregate files are up to date. In particular, the webpage workflow has updated information available.
