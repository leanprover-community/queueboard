#!/usr/bin/env bash

# This script processes a JSON file containing pull request data and generates a table.
# The table maps github handles `X`, to a list of pairs `(number, state)`,
# where `number` is a PR number assigned to `X`,
# and `state` is the state of that PR (open/closed).

# Usage: ./assign_data.sh

jq '
  reduce .pr_statusses[] as $pr (
    {}; 
    reduce $pr.assignees[] as $assignee (
      .; 
      .[$assignee] += [{"number": $pr.number, "state": $pr.state}]
    )
  )
' processed_data/aggregate_pr_data.json
