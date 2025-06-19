#!/bin/bash

set -e

if [[ ! -f ".runner" ]]; then
  if [[ -z "$GITHUB_REPO" || -z "$RUNNER_TOKEN" ]]; then
    echo "Missing GITHUB_REPO or RUNNER_TOKEN"
    exit 1
  fi

  ./config.sh \
    --url "${GITHUB_REPO}" \
    --token "${RUNNER_TOKEN}" \
    --unattended \
    --replace
fi

./run.sh

# sudo apt update