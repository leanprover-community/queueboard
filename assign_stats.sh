#!/usr/bin/env bash

# This script processes a JSON file containing pull request data and generates a table.
# The table includes the assignee, the number of open PRs, the number of PRs with a number greater than N, and the total number of PRs assigned to each assignee.

# Usage: ./assign_stats.sh [N]
# If N is not provided, it defaults to the largest PR number in the dataset minus 1000.
# Example: ./script.sh 10020

# Get the largest PR number in the dataset
LARGEST_PR=$(jq '.pr_statusses | max_by(.number) | .number' processed_data/aggregate_pr_data.json)

# Set N to the user-provided value or default to largest PR number minus 1000
N=${1:-$((LARGEST_PR - 1000))}

# Step 1: Compute the lengths of the lists
LENGTHS_DATA=$(./assign_data.sh | jq --argjson N "$N" '
  to_entries | map({
    assignee: .key,
    open: (.value | map(select(.state == "open")) | length),
    total: (.value | length),
    greater_than_N: (.value | map(select(.number > $N)) | length)
  })
')

# Step 2: Print the data as a TSV table
echo "$LENGTHS_DATA" | jq -r '
  (.[] | [.assignee, .open, .greater_than_N, .total] | @tsv)
' | column -t -s $'\t'
