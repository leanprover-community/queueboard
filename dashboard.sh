#!/usr/bin/env bash

# Surface errors in this script to CI, so they get noticed.
# See e.g. http://redsymbol.net/articles/unofficial-bash-strict-mode/ for explanation.
set -e -u -o pipefail

# The date and time, 24 hours ago, in the ISO8601 format
yesterday=$(date -u -d "24 hours ago" '+%Y-%m-%dT%H:%M:%SZ')
# The date and time, 7 days ago, in the ISO8601 format
aweekago=$(date -u -d "7 days ago" '+%Y-%m-%dT%H:%M:%SZ')

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
queue_labels="-label:blocked-by-other-PR -label:merge-conflict -label:awaiting-CI -label:awaiting-author -label:WIP -label:delegated -label:auto-merge-after-CI"
QUERY_QUEUE=$(prepare_query "sort:updated-asc is:pr state:open -is:draft -status:failure $queue_labels")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE" | jq '{"output": .}' > queue.json

# Query Github API for all pull requests in the queue that are labelled `new-contributor`.
QUERY_QUEUE_NEWCONTRIBUTOR=$(prepare_query "sort:updated-asc is:pr state:open label:new-contributor $queue_labels")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE_NEWCONTRIBUTOR" | jq '{"output": .}' > queue-new-contributor.json

# Query Github API for all pull requests with a merge conflict, that would be otherwise ready for review
QUERY_QUEUE_BUT_MERGE_CONFLICT=$(prepare_query "sort:updated-asc is:pr state:open -is:draft -status:failure -label:blocked-by-other-PR -label:awaiting-CI -label:awaiting-author -label:WIP -label:delegated -label:auto-merge-after-CI label:merge-conflict")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE_BUT_MERGE_CONFLICT" | jq '{"output": .}' > needs-merge.json

# Query Github API for all pull requests that are labeled `ready-to-merge` and have not been updated in 24 hours.
QUERY_READYTOMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:ready-to-merge updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_READYTOMERGE" | jq '{"output": . }' > ready-to-merge.json
# Query Github API for all pull requests that are labeled `auto-merge-after-CI` and have not been updated in 24 hours.
QUERY_AUTOMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:auto-merge-after-CI updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_AUTOMERGE" | jq '{"output": . }' > automerge.json

# Query Github API for all pull requests that are labeled `maintainer-merge` but not `ready-to-merge` and have not been updated in 24 hours.
QUERY_MAINTAINERMERGE=$(prepare_query "sort:updated-asc is:pr state:open label:maintainer-merge -label:ready-to-merge updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_MAINTAINERMERGE" | jq '{"output": .}' > maintainer-merge.json

# Query Github API for all ready pull requests that are labeled `awaiting-zulip`.
QUERY_NEEDS_DECISION=$(prepare_query "sort:updated-asc is:pr -is:draft state:open label:awaiting-zulip")
gh api graphql --paginate --slurp -f query="$QUERY_NEEDS_DECISION" | jq '{"output": .}' > needs-decision.json

# Query Github API for all pull requests that are labeled `delegated` and have not been updated in 24 hours.
QUERY_DELEGATED=$(prepare_query "sort:updated-asc is:pr state:open label:delegated updated:<$yesterday")
gh api graphql --paginate --slurp -f query="$QUERY_DELEGATED" | jq '{"output": .}' > delegated.json

# Query Github API for all pull requests that are labeled `new-contributor` and have not been updated in seven days.
# Sadly, this includes all PRs which are in the review queue...
QUERY_NEWCONTRIBUTOR=$(prepare_query "sort:updated-asc is:pr state:open label:new-contributor updated:<$aweekago")
gh api graphql --paginate --slurp -f query="$QUERY_NEWCONTRIBUTOR" | jq '{"output": .}' > new-contributor.json

# Query Github API for all pull requests that are labeled `help-wanted`.
QUERY_HELP_WANTED=$(prepare_query "sort:updated-asc is:pr state:open label:help-wanted")
gh api graphql --paginate --slurp -f query="$QUERY_HELP_WANTED" |	jq '{"output": .}' > help-wanted.json
# Query Github API for all pull requests that are labeled `please-adopt`.
QUERY_PLEASE_ADOPT=$(prepare_query "sort:updated-asc is:pr state:open label:please-adopt")
gh api graphql --paginate --slurp -f query="$QUERY_PLEASE_ADOPT" | jq '{"output": .}' > please-adopt.json

# Query Github API for all open pull requests which are ready (without a WIP label or draft status).
QUERY_READY=$(prepare_query 'sort:updated-asc is:pr -is:draft state:open -label:WIP')
gh api graphql --paginate --slurp -f query="$QUERY_READY" | jq '{"output": .}' > all-ready-PRs.json

# Query Github API for all open pull requests which are in draft status
QUERY_DRAFT=$(prepare_query 'sort:updated-asc is:pr is:draft state:open')
gh api graphql --paginate --slurp -f query="$QUERY_DRAFT" | jq '{"output": .}' > all-draft-PRs.json

# List of JSON files: their order does not matter for the generated output.
# NB: we purposefully do not add 'all-ready-PRs' or 'all-draft-PRs' to this list,
# as each PR means an additional API call, and we don't need this specific information here
json_files=("queue.json" "queue-new-contributor.json" "needs-merge.json" "ready-to-merge.json" "automerge.json" "maintainer-merge.json" "needs-decision.json" "delegated.json" "new-contributor.json" "help-wanted.json" "please-adopt.json")

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

python3 ./dashboard.py $pr_info "all-ready-PRs.json" "all-draft-PRs.json" ${json_files[*]} > ./dashboard.html

rm *.json

