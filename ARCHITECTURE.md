# Overall architecture of this repository

This document describes the high-level architecture of the review dashboard. If you want to familiarize yourself with the code base, you are just in the right place!

## High-level overview
This repository contains two separate, but related pieces of code.

The first half (the "backend") is infrastructure to query and download metadata about pull request on *mathlib*, tracking their state over time. (This covers all open pull requests, but --- as of February 2025 --- not all past PRs yet.)
A github workflow periodically checks for updates on pull requests and downloads the current data for all pull requests with updates. This data is tracked in the repository: hence, this repository also functions as a cache of information, allowing to only download meta-data for updated PRs (as opposed to downloading all PRs' data each time the dashboard is re-generated).

The second half (the "frontend") contains scripts and a github workflow to generate the mathlib triage and review dashboard, using the data from the previous step. Generating this dashboard proceeds by
- generating a static webpage from this information
- publishing the webpage using github pages
These steps also are run regularly, using a cronjob.

As of February 2025, these steps are always run next to each other, every 8 minutes. Right after the backend data is updated, the webpage is regenerated accordingly. One workflow run takes about 3 minutes --- so all in all, this means the data on the dashboard has a latency of around ten minutes.
(There are future plans to make both the downloading of updated metadata more "push-driven" (i.e., a PR update triggering a re-download automatically), which would allow for faster webpage updates.)


## Relevant files
This section talks briefly about various important directories and data structures. Pay attention to the Architecture Invariant sections. They often talk about things which are deliberately absent in the source code.

**The backend: data gathering infrastructure**
The `data` directory contains all downloaded data for all pull requests to the *mathlib* repository: this ought to contain data for all open pull requests. Data for closed pull requests is gradually being included (but currently, data for many such PRs is still missing).
**Invariant.** All contents in `data` is directly downloaded using the Github API. Any post-processing of data happens in a separate directory. Apart from downloading, the `data` directory is only modified to remove broken data. If the repository contains any temporary files left from partial downloads, that is a bug in the downloading script.

The `processed_data` directory contains results of data post-processing scripts. Currently, there are three such files, each generated by `process.py`.
- `all_pr_data.json` contains certain overview information for every PR with metadata in this repository
- `open_pr_data.json` contains the same information, but only for the subset of currently open PRs
- `assignment_data.json` collects which PRs are assigned to which github user
- `infinity_cosmos_data.json` is an experimental file, gathering statistics about PRs from the infinity-cosmos project. It may be removed in the future.

This post-processing includes merely extracting relevant information, but also some non-trivial analyses. For instance, for each PR, we try to determine the total time it was on the review queue and the last time its status changed (from e.g. awaiting author action to waiting on review).

There are a few text files which hold state, about missing PRs or PRs which might need special handling.
- `missing_prs.txt` lists open PRs for which data is entirely missing
(This could happen, for example, if there is an error in the downloading workflow. In practice, this is rare.)
It also contains comments if downloading a PR's data failed already: if downloading a PR's data failed for three times in a row,
the PR is marked as "stubborn" and listed in `stubborn_prs.txt` instead.
- `stubborn_prs.txt` lists PRs for which we only download reduced metadata. (Some PRs have so many commits, for example, that downloading metadata for all of these would lead to the download timing out.) Less than 1% of all PRs are marked stubborn.
- `closed_prs_to_backfill.txt` lists PRs which were closed a while ago: we want to collect their data, but this is not urgent.
- `redownload.txt` contains PRs for which valid data exists, but that data is outdated: the current data should be downloaded again, but in the mean-time, we can keep the data we have

`check_data_integrity.py` is a script to verify the contents of the downloaded data, and detect broken data. It performs a variety of small tasks
- detect broken json files (and automatically removes them), marking PRs as stubborn if necessary
- detect PRs whose data is surely out of date (and schedules them for re-downloading)
- prunes obsolete entries from `missing_prs.txt` and `closed_prs_to_backfill.txt`
- compares PR data from the aggregate files and the current REST API calls, and highlights differences which suggest out-of-date PR data

This script depends on quite a bit of file state:
- the entire `data` directory
- the aggregate json files
- all text files about files to (re-)download
- input files `all-open-prs-{1,2}.json` with current data about all open PRs,
  to compare this with the data in the aggregate files
It modifies these *.txt files, and deletes any directories in `data` with obsolete data.

The actual downloading of new or updated metadata happens through two scripts.
- `scripts/download_missing_outdated_PRs.sh` uses the information in the *.txt files to download metadata
for missing PRs, and re-downloads data for PRs marked as such. If successful, it empties the file `redownload.txt`.
- `scripts/gather_stats.sh` queries the github API for all PRs updated in the past N minutes and downloads the data for all of them (overwriting any previous data).
- `gather_stats_single.yml` is currently unused; TODO document what it is meant to do!

All of this is orchestrated in the `update_metadata.yml` workflow, which calls the above scripts.
**Invariant.** This is the only workflow which pushes modifies `data`, `processed_data` or the *.txt files on the master branch. The other workflow only updates the `gh-pages` branch.

See `docs/Workflow ordering and design.md` for more detailed considerations of the workflow split, and describing the current architecture.

**The frontend: generating webpages**
The main entry point to the frontend is a shell script `dashboard.sh`.
- it queries github's API for current data on the open pull requests, saving the output into two JSON files
- it then calls `dashboard.py` (with the JSON files passed as explicit arguments) to create a dashboard.
The data in the json files conceptually duplicates the aggregate data downloaded in the backend. (It is present to allow comparing the two data sources, detecting mismatches or stale data earlier.) In the future, the first step should be removed, and `dashboard.py` should operate purely on the data downloaded in the backend part.

**Architecture invariant.** All network requests happen in the backend or in this script.
`dashboard.py` makes no connections to the network.

`dashboard.py` is where the core logic of creating the dashboard lives. It is a Python script, taking the JSON files from the previous step and the processed PR information in `processed_data` as input. It writes the HTML code for the dashboard page, and various subpages, to hard-coded HTML files. The overall work is split across a few files.
- `mathlib_dashboards.py` defines the various dashboards which are present on the generated HTML page
- `compute_dashboard_prs.py` contains the logic for computing which PRs belong to each dashboard in `mathlib_dashboards.py`

**Architecture invariant.** The output of `dashboard.py` only depends on its command line arguments, the contents of the `processed_data` directory and its current time: with both fixed, it is deterministic. In particular, it makes no network requests. All reading of input files is constrained to one method `read_json_files` in the beginning.

`generate_assignment_page.py` is a separate script generating a webpage `assign_reviewers.html` suggesting reviewers to assign to unassigned pull requests. This page is not generated by default, as it is aimed at mathlib maintainers.

`.github/workflows/regenerate_dashboard.yml` defines the workflow updating the dashboard. It runs the above scripts to generate an up-to-date dashboard, and commits the updated HTML file on the `gh-pages` branch. That branch is deployed by github pages to create the webpage.
**Invariant.** This workflow only writes to the `gh-pages` branch. It only reads data from the master branch.

`style.css` contains all style rules for the generated webpage

`util.py` contains two functions which are needed in otherwise unrelated scripts

`classify_pr_state.py` contains logic to classify a pull request as ready for review, awaiting action by the author, blocked on another PR, etc. This is used to generate a statistics section on the dashboard, and also to determine a PR's status change over time.
`docs/FAQ_pr_state_classification.md` documents some particular decisions related to this classification.

`state_evolution.py` contains an algorithm to determine a PR's status changes over time, and derive e.g. the total time a PR was on the review queue, the first time this happened (if any) or the last time a PR's status changed.
`test_state_evolution.py` contains unit tests for the algorithm in `state_evolution.py`

`ci_status.py` defines a shared enumeration used for the data processing, and the dashboard.

`test` contains versions of all input files to this script, at some point in time. These can be used for locally testing `dashboard.py`.

`send-zulip-dm.py` contains code for sending a direct message on zulip. This is currently unused, but may be used by `generate_assignment_page.py` in the future.


# Cross-cutting concerns

## Limiting github API calls
Each github API call is expensive: github (understandably) adds rate limiting to each call to its API: successive calls can happen at most once per second. This imposes a natural lower bound on the execution time of this script.
In particular, each query for each dashboard takes one second: if easily possible/the data for a particular dashboard can be easily derived (e.g., filtered) from existing data, avoiding an API call and a separate JSON file is preferred.

## Testing
There are several levels at which this project can be tested. Currently, there are no *automated* tests, but an effort is made that the dashboard logic can easily be tested manually.

- `classify_pr_state.py` has unit tests: to run them, use e.g. `nose` (which will pick them up automatically), or run `python3 classify_pr_state.py`
- `state_evolution.py` has unit tests in the file `test_state_evolution.py`: running either `python3 test_state_evolution.py` or `nose` will run them

Changes to just `dashboard.py` can be tested using the JSON files in the `test` directory.
Doing so requires a one-time set-up step: create a copy of the two relevant test files in the top-level directory. For instance, you can run `ln test/all-open-PRs-1.json all-open-PRs-1.json && ln test/all-open-PRs-2.json all-open-PRs-2.json`. (Another option is simply copying over these files.)
Once this is done, you can run `python3 dashboard.py all-open-PRs-1.json all-open-PRs-2.json` (in the top-level directory) to execute the script. If you just want to test everything still works, you're done.
Caution: to view the generated file, make sure to read the file in the top-level directory (otherwise, the .css file is not found.)

If you want to ensure the generated output didn't change (or check if you made subtle mistakes), you can use `diff` or a similar tool to compare the generated files before and after the change. For instance, the testing step would become
- run `mkdir -p before && cp *.html before` before performing your changes; this copies the current .html files to the `before` directory
- change the script; run `python3 dashboard.py all-open-PRs-1.json all-open-PRs-2.json` as above. Repeat this until you're happy.
- run `mkdir -p after && cp *.html after` to copy the new files; now you can compare the `before` and `after` directories.


**TODO**: document additional tools for testing like `mypy`, `ruff check` and `ruff format`, `isort`
