#!/usr/bin/env bash

# Download PRs which were manually marked as outdated or needed for re-download.

# Surface errors in this script to CI, so they get noticed.
# See e.g. http://redsymbol.net/articles/unofficial-bash-strict-mode/ for explanation.
set -e -u -o pipefail

# GitHub repository details
REPO="leanprover-community/mathlib4"
API_URL="https://api.github.com/repos/$REPO/pulls"

CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Parse the list of all stubborn PRs. This is newline-separated,
# but for our purposes, that is fine.
stubborn_prs=$(cat "stubborn_prs.txt" | grep --invert-match "^--")

# |download_normal $pr| downloads 'normal' info for the PR '$pr' into the appropriate directory.
# Do not use with stubborn PRs: usually, this would time out.
function download_normal {
    local dir="data/$1"
    mkdir -p "$dir"
    # Run pr_info.sh and pr_reactions.sh and save the output.
    # "parse error: Invalid numeric literal at line N, column M'" comes from jq complaining about e.g. an empty file
    ./pr_info.sh "$1" | jq '.' > "$dir/pr_info.json"
    ./pr_reactions.sh "$1" | jq '.' > "$dir/pr_reactions.json"
    # Save the current timestamp.
    echo "$CURRENT_TIME" > "$dir/timestamp.txt"
}

# |download_stubborn $pr| downloads "stubborn" info for the PR '$pr' into the appropriate directory.
function download_stubborn {
  local dir="data/$1-basic"
  mkdir -p "$dir"
  ./basic_pr_info.sh "$1" | jq '.' > "$dir/basic_pr_info.json"
  echo "$CURRENT_TIME" > "$dir/timestamp.txt"
}

# |download_pr $pr| downloads information for the PR $pr into the appropriate directory.
# It consults $stubborn_prs to determine whether to treat a PR as stubborn or not.
function download_pr {
  if [[ $stubborn_prs == *$1* ]]; then
    download_stubborn $1
  else
    download_normal $1
  fi
}

# Re-download data if missing. Take care to not ask for too much at once!
# FIXME: this is only somewhat robust --- improve this to ensure to avoid
# re-re-downloading in a loop!
for pr in $(cat "redownload.txt"); do
  echo "About to re-download PR $pr"
  download_pr $pr
done
echo "" > redownload.txt
echo "Successfully re-downloaded all planned PRs (if any)"

# In case there are PRs which got "missed" somehow, backfill data for up to one of them.
i=0
for pr in $(cat "missing_prs.txt" | grep --invert-match "^--" | head --lines 50); do
  # Check if the directory exists
  if [ -d "data/$pr" ]; then
    echo "[skip] Data exists for #$pr: $CURRENT_TIME"
    continue
  fi
  if [ $i -eq 1 ]; then
    break;
  fi
  i=$((i+1))
  echo "Attempting to backfill data for PR $pr"
  download_pr $pr
done
# If there was no "missing" PR to backfill, backfill at most one PR from `closed_prs_to_backfill.txt`.
if [ $i -eq 0 ]; then
  for pr in $(cat "closed_prs_to_backfill.txt" | grep --invert-match "^--" | head --lines 50); do
    # Check if the directory exists
    if [ -d "data/$pr" ]; then
      echo "[skip] Data exists for #$pr: $CURRENT_TIME"
      continue
    elif [ -d "data/$pr-basic" ]; then
      # If such a PR is ever classified as stubborn, it should be removed from this file:
      # this scenario should never happen. Let's be extra safe just in case.
      echo "unexpected: closed PR to backfill is stubborn!"
      echo "[skip] Data exists for 'stubborn' PR $pr: $CURRENT_TIME"
      continue
    fi
    echo "Attempting to backfill data for PR $pr"
    download_normal $pr
    break
  done
fi
echo "Backfilled at most one PR successfully"

# Do the same for at most 2 stubborn PRs.
# (Using `head --lines 2` is *not* equivalent, as we want to count *non-skipped* PRs.)
i=0
for pr in $stubborn_prs; do
  # Check if the directory exists.
  if [ -d "data/$pr-basic" ]; then
    echo "[skip] Data exists for 'stubborn' PR #$pr: $CURRENT_TIME"
    continue
  fi
  echo "Attempting to backfill data for 'stubborn' PR $pr"
  download_stubborn $pr
  i=$((i+1))
  if [ $i -eq 2 ]; then
    break;
  fi
done
echo "Backfilled up to two 'stubborn' PRs successfully"
