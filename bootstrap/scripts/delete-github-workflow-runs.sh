#!/bin/bash

set -eoux pipefail

# gh run list --workflow  .github/workflows/flux-bootstrap.yml
OWNER=$GITHUB_DEMO_REPO_OWNER
REPO=$GITHUB_DEMO_REPO_NAME
WORKFLOW_FILE=".github/workflows/flux-bootstrap.yml"


RUN_IDS=$(gh run list --workflow "$WORKFLOW_FILE" --json databaseId -q '.[].databaseId')

# Check if any runs were found
if [ -z "$RUN_IDS" ]; then
  echo "No workflow runs found for $WORKFLOW_FILE."
  exit 0
fi

echo "Deleting workflow runs for $WORKFLOW_FILE..."

# Iterate and delete each run
for id in $RUN_IDS; do
  echo "Deleting run ID: $id"
  gh api -X DELETE "repos/$OWNER/$REPO/actions/runs/$id"
done

echo "Deletion complete."
