#!/usr/bin/env bash

# Download detailed PR information for a given list of PRs.
# This script returns the exit code
# - 0 if no errors occurred, and data for at least one PR was downloaded,
# - 1 if the was an error fetching data.
#
# See https://github.com/jcommelin/gh-mathlib-metadata/blob/master/backfill.sh
# for a previous version of this script, which would download information for
# all pull requests numbered in a given interval.

# Surface errors in this script to CI, so they get noticed.
# See e.g. http://redsymbol.net/articles/unofficial-bash-strict-mode/ for explanation.
set -e -u -o pipefail

CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# We iterate over each argument, assume it is a PR number
# and attempt to download data for that numbered PR.

# This script does not perform any rate limiting: make sure to do so yourself!

stubborn_prs=$(cat "../stubborn_prs.txt" | grep --invert-match "^--" | sort | uniq)

# NB: keep this function in sync with download_missing_outdated_PRs.sh
# |download_normal $pr| downloads 'normal' info for the PR '$pr' into the appropriate directory.
# Do not use with stubborn PRs: usually, this would time out.
function download_normal {
    local dir="data/$1"
    local tmpdir="data/$1-temp"
    mkdir -p "$tmpdir"
    # Run pr_info.sh and pr_reactions.sh and save the output.
    # "parse error: Invalid numeric literal at line N, column M'" comes from jq complaining about e.g. an empty file.

    # Save the output to a temporary directory, which we delete in case anything goes wrong.
    { ./pr_info.sh "$1" | jq '.' > "$tmpdir/pr_info.json"; } || { rm -r -f $tmpdir && return 1; }
    # Save the current timestamp.
    echo "$CURRENT_TIME" > "$tmpdir/timestamp.txt"
    { ./pr_reactions.sh "$1" | jq '.' > "$tmpdir/pr_reactions.json"; } || { rm -r -f $tmpdir && return 1; }
    rm -r -f $dir
    mv -f $tmpdir/ $dir/
}

for prnumber in "$@"
do
  if [[ $stubborn_prs == *$prnumber* ]]; then
    echo "PR $prnumber is stubborn: backfilling these is not supported yet!"
  else
    echo "Backfilling/re-downloading data for PR #$prnumber"
    download_normal $prnumber
  fi
done

echo "Backfilling/re-downloading run completed successfully"
