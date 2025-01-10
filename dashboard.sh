#!/usr/bin/env bash

# Surface errors in this script to CI, so they get noticed.
# See e.g. http://redsymbol.net/articles/unofficial-bash-strict-mode/ for explanation.
set -e -u -o pipefail

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

# Query Github API for all open pull requests:
# split in two as the REST-based API only returns up to 1000 items.
QUERY_ALLOPEN1=$(prepare_query 'sort:updated-asc is:pr state:open -label:merge-conflict')
QUERY_ALLOPEN2=$(prepare_query 'sort:updated-asc is:pr state:open label:merge-conflict')
gh api graphql --paginate --slurp -f query="$QUERY_ALLOPEN1" | jq '{"output": .}' > all-open-PRs-1.json
gh api graphql --paginate --slurp -f query="$QUERY_ALLOPEN2" | jq '{"output": .}' > all-open-PRs-2.json

# TEMPORARILY download the old files for the queue and "just a merge conflict", to compare results.
queue_labels_but_merge="-label:blocked-by-other-PR -label:blocked-by-core-PR -label:blocked-by-batt-PR -label:blocked-by-qq-PR -label:awaiting-CI -label:awaiting-author -label:awaiting-zulip -label:please-adopt -label:help-wanted -label:WIP -label:delegated -label:auto-merge-after-CI -label:ready-to-merge"
QUERY_QUEUE=$(prepare_query "sort:updated-asc is:pr state:open -is:draft status:success base:master $queue_labels_but_merge -label:merge-conflict")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE" | jq '{"output": .}' > queue.json
