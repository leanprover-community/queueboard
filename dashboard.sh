#!/usr/bin/env bash

# The date and time, 24 hours ago, in the ISO8601 format
yesterday=$(date -u -d "24 hours ago" '+%Y-%m-%dT%H:%M:%SZ')

prepare_query () {
	echo "
query(\$endCursor: String) {
  search(query: \"repo:leanprover-community/mathlib4 $1\", type: ISSUE, first: 25, after: \$endCursor) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on PullRequest {
        number
	url
	author { ... on User { login url } }
	title
        state
	updatedAt
        labels(first: 10, orderBy: {direction: DESC, field: CREATED_AT}) {
          nodes {
            name
	    color
	    url
          }
        }
      }
    }
  }
}
	";
}

# Query Github API for all pull requests that are on the #queue.
# So we want to list all pull requests that are
# - open, not draft
# - do not have status:failure
# - do not have any of the following labels: blocked-by-other-PR, merge-conflict, awaiting-CI, WIP, awaiting-author, delegated, auto-merge-after-CI
QUERY_QUEUE=$(prepare_query "sort:updated-asc is:pr state:open -is:draft -status:failure -label:blocked-by-other-PR -label:merge-conflict -label:awaiting-CI -label:awaiting-author -label:WIP -label:delegated -label:auto-merge-after-CI")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE" |\
	jq '{"output": ., "title": "Queue"}' > queue.json


# Query Github API for all pull requests that are labeled `ready-to-merge` and have not been updated in 24 hours.
QUERY_READYTOMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:ready-to-merge updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_READYTOMERGE" |\
	jq '{"output": ., "title": "Stale ready-to-merge"}' > ready-to-merge.json

# Query Github API for all pull requests that are labeled `maintainer-merge` but not `ready-to-merge` and have not been updated in 24 hours.
QUERY_MAINTAINERMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:maintainer-merge -label:ready-to-merge updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_MAINTAINERMERGE" |\
	jq '{"output": ., "title": "Stale maintainer-merge"}' > maintainer-merge.json

# Query Github API for all pull requests that are labeled `delegated` and have not been updated in 24 hours.
QUERY_READYTOMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:delegated updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_READYTOMERGE" |\
	jq '{"output": ., "title": "Stale delegated"}' > delegated.json

# Query Github API for all pull requests that are labeled `new-contributor` and have not been updated in 24 hours.
QUERY_NEWCONTRIBUTOR=$(prepare_query "sort:updated-asc is:pr state:open label:new-contributor updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_NEWCONTRIBUTOR" |\
	jq '{"output": ., "title": "Stale new-contributor"}' > new-contributor.json

# List of JSON files
json_files=("queue.json" "ready-to-merge.json" "maintainer-merge.json" "delegated.json" "new-contributor.json")

# Output file
pr_info="pr-info.json"

# Empty the output file
echo "{}" > $pr_info

# Create an empty array to store PR numbers
declare -A pr_numbers

# For each JSON file
for json_file in "${json_files[@]}"
do
  # Get the PR numbers and add them to the array
  while read -r pr_number; do
    pr_numbers["$pr_number"]=1
  done < <(jq -r '.output[]["data"]["search"]["nodes"][]["number"]' $json_file)
done

# For each unique PR number
for pr_number in "${!pr_numbers[@]}"
do
  # Get the diff info
  diff_info=$(gh api repos/leanprover-community/mathlib4/pulls/$pr_number)

  # # Get the additions, deletions, and changed files
  # additions=$(echo $diff_info | jq '.additions')
  # deletions=$(echo $diff_info | jq '.deletions')
  # changed_files=$(echo $diff_info | jq '.changed_files')

  # Add the diff info to the output file
  jq --arg pr_number "$pr_number" --argjson diff_info "$diff_info" \
    '.[$pr_number] = $diff_info' $pr_info > temp.json && mv temp.json $pr_info
  # jq --arg pr_number "$pr_number" --argjson additions "$additions" --argjson deletions "$deletions" --argjson changed_files "$changed_files" \
  #   '.[$pr_number] = {additions: $additions, deletions: $deletions, changed_files: $changed_files}' $pr_info > temp.json && mv temp.json $pr_info
done

python3 ./dashboard.py $pr_info ${json_files[*]} > ./dashboard.html

rm *.json

