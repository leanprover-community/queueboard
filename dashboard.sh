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
QUERY_ALLOPEN1=$(prepare_query 'sort:updated-asc is:pr state:open -is:draft')
QUERY_ALLOPEN2=$(prepare_query 'sort:updated-asc is:pr state:open is:draft')
gh api graphql --paginate --slurp -f query="$QUERY_ALLOPEN1" | jq '{"output": .}' > all-open-PRs-1.json
gh api graphql --paginate --slurp -f query="$QUERY_ALLOPEN2" | jq '{"output": .}' > all-open-PRs-2.json

python3 ./dashboard.py "all-open-PRs-1.json" "all-open-PRs-2.json" > ./index.html

rm *.json
