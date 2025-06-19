#!/bin/bash

set -e

if [ $# -ne 3 ]; then
  echo "Usage: $0 <runner-id> <github-repo-url> <runner-token>"
  exit 1
fi

RUNNER_ID="$1"
GITHUB_REPO="$2"
RUNNER_TOKEN="$3"

# Label-friendly timestamp
CREATED_AT=$(date +%s)

# Start container
podman run -d \
  --name "gh-runner-${RUNNER_ID}" \
  --label role=github-runner \
  --label runner_id="${RUNNER_ID}" \
  --label created_at="${CREATED_AT}" \
  -e GITHUB_REPO="${GITHUB_REPO}" \
  -e RUNNER_TOKEN="${RUNNER_TOKEN}" \
  github-actions

echo "Started GitHub runner container: gh-runner-${RUNNER_ID}"
