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
# We skip PRs which already have *any* data present (even erronerous JSON files, outdated files
# or just some of the files): such advanced checks are left to other scripts.

for prnumber in "$@"
do
  # Check if the directory exists
  if [ -d "data/$prnumber" ]; then
    echo "[skip] Data exists for PR #$prnumber: $CURRENT_TIME"
    continue
  fi
  CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "Backfilling PR #$prnumber: $CURRENT_TIME"

  # Create the directory for the PR.
  dir="data/$pr"
  mkdir -p "$dir"

  # Run pr_info.sh and save the output.
  ./pr_info.sh "$pr" | jq '.' > "$dir/pr_info.json"

  # Run pr_reactions.sh and save the output.
  ./pr_reactions.sh "$pr" | jq '.' > "$dir/pr_reactions.json"

  # Save the current timestamp.
  echo "$CURRENT_TIME" > "$dir/timestamp.txt"

  # Sleep for 2 minutes to avoid rate limiting.
  sleep 2m
done

echo "Backfilling run completed successfully"
