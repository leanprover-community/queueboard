#!/usr/bin/env bash

# Gather updated PR information for all mathlib PRs which were updated "recently".
# This script returns the exit code
# - 0 if no errors occurred, and data for at least one PR was downloaded,
# - 1 if the was an error fetching data.

# Surface errors in this script to CI, so they get noticed.
# See e.g. http://redsymbol.net/articles/unofficial-bash-strict-mode/ for explanation.
set -e -u -o pipefail

TIMEDELTA=$1

# Change to the directory where the script is located
cd "$(dirname "$0")"

# GitHub repository details
REPO="leanprover-community/mathlib4"
API_URL="https://api.github.com/repos/$REPO/pulls"

# Get the current timestamp and the timestamp from TIMEDELTA minutes ago
CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PAST_TIME=$(date -u -d "$TIMEDELTA minutes ago" +"%Y-%m-%dT%H:%M:%SZ")

# Fetch the list of pull requests
response=$(curl -s "$API_URL?state=all&per_page=100")

# Check if the response is not empty
if [ -z "$response" ]; then
  echo "Failed to fetch PR data: $CURRENT_TIME"
  exit 1
fi

# Parse the JSON response and filter PRs updated in the last TIMEDELTA minutes
prs=$(echo "$response" | jq -r --arg PAST_TIME "$PAST_TIME" --arg CURRENT_TIME "$CURRENT_TIME" '
  .[] | select(.updated_at >= $PAST_TIME and .updated_at <= $CURRENT_TIME) |
  .number
')

# Parse the list of all stubborn PRs. This is newline-separated,
# but for our purposes, that is fine.
stubborn_prs=$(cat stubborn_prs.txt | grep --invert-match "^-")

# Download data for all updated PRs, overwriting existing data if needed.
for pr in $prs; do
  if [[ $stubborn_prs == *$pr* ]]; then
    dir="data/$pr-basic"
    mkdir -p "$dir"
    ./basic_pr_info.sh "$pr" | jq '.' > "$dir/basic_pr_info.json"
    echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  else
    dir="data/$pr"
    mkdir -p "$dir"
    # Run pr_info.sh and pr_reactions.sh and save the output.
    ./pr_info.sh "$pr" | jq '.' > "$dir/pr_info.json"
    ./pr_reactions.sh "$pr" | jq '.' > "$dir/pr_reactions.json"
    # Save the current timestamp.
    echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  fi
done

# Re-download data if missing. Take care to not ask for too much at once!
# (If chunking, make sure to not run into a loop of re-re-downloading in a loop!)
for pr in $(cat "redownload.txt"); do
  echo "About to re-download PR $pr"
  if [[ $stubborn_prs == *$pr* ]]; then
    dir="data/$pr-basic"
    mkdir -p "$dir"
    ./basic_pr_info.sh "$pr" | jq '.' > "$dir/basic_pr_info.json"
    echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  else
    dir="data/$pr"
    mkdir -p "$dir"
    # Run pr_info.sh and pr_reactions.sh and save the output.
    ./pr_info.sh "$pr" | jq '.' > "$dir/pr_info.json"
    ./pr_reactions.sh "$pr" | jq '.' > "$dir/pr_reactions.json"
    # Save the current timestamp.
    echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  fi
done
echo "" > redownload.txt
echo "Successfully re-downloaded all planned PRs (if any)"

# In case there are PRs which got "missed" somehow, backfill
# data for up to one of them.
i=0
for pr in $(cat "missing_prs.txt"); do
  # Check if the directory exists
  if [ -d "data/$pr" ]; then
    echo "[skip] Data exists for #$pr: $CURRENT_TIME"
    continue
  fi
  echo "Attempting to backfill data for PR $pr"
  dir="data/$pr"
  mkdir -p "$dir"
  # Run pr_info.sh and pr_reactions.sh and save the output.
  ./pr_info.sh "$pr" | jq '.' > "$dir/pr_info.json"
  ./pr_reactions.sh "$pr" | jq '.' > "$dir/pr_reactions.json"
  # Save the current timestamp.
  echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  i=$((i+1))
  if [ $i -eq 1 ]; then
    echo "Backfilled one PR successfully, exiting"
    break;
  fi
done

# Do the same for at most one stubborn PR.
j=0
for pr in $stubborn_prs; do
  dir="data/$pr-basic"
  # Check if the directory exists.
  if [ -d $dir ]; then
    echo "[skip] Data exists for 'stubborn' PR #$pr: $CURRENT_TIME"
    continue
  fi
  echo "Attempting to backfill data for 'stubborn' PR $pr"
  mkdir -p "$dir"
  ./basic_pr_info.sh "$pr" | jq '.' > "$dir/basic_pr_info.json"
  echo "$CURRENT_TIME" > "$dir/timestamp.txt"
  j=$((j+1))
  if [ $j -eq 1 ]; then
    echo "Backfilled one 'stubborn' PR successfully, exiting"
    break;
  fi
done
