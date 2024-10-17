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

# Query Github API for all pull requests that are on the #queue.
# So we want to list all pull requests that are
# - open, not draft
# - has status:success (which excludes failing or in-progress CI)
# - do not have any of the following labels: blocked-by-other-PR, merge-conflict, awaiting-CI, WIP, awaiting-author, awaiting-zulip, help-wanted, please-adopt delegated, auto-merge-after-CI, ready-to-merge
queue_labels_but_merge="-label:blocked-by-other-PR -label:awaiting-CI -label:awaiting-author -label:awaiting-zulip -label:please-adopt -label:help-wanted -label:WIP -label:delegated -label:auto-merge-after-CI -label:ready-to-merge"
QUERY_QUEUE=$(prepare_query "sort:updated-asc is:pr state:open -is:draft status:success base:master $queue_labels_but_merge -label:merge-conflict")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE" | jq '{"output": .}' > queue.json

# Query Github API for all pull requests with a merge conflict, that would be otherwise ready for review.
QUERY_QUEUE_BUT_MERGE_CONFLICT=$(prepare_query "sort:updated-asc is:pr state:open -is:draft status:success base:master $queue_labels_but_merge label:merge-conflict")
gh api graphql --paginate --slurp -f query="$QUERY_QUEUE_BUT_MERGE_CONFLICT" | jq '{"output": .}' > needs-merge.json

# Query Github API for all open pull requests
QUERY_ALLOPEN=$(prepare_query 'sort:updated-asc is:pr state:open')
gh api graphql --paginate --slurp -f query="$QUERY_ALLOPEN" | jq '{"output": .}' > all-open-PRs.json

python3 ./dashboard.py "all-open-PRs.json" "queue.json" "needs-merge.json" > ./index.html

rm *.json
