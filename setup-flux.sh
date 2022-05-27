#!/bin/bash

set -eou pipefail

# repo per team
# https://fluxcd.io/docs/guides/repository-structure/#repo-per-team

# *github* flux bootstrap uses PAT for auth. For using SSH follow
# *generic git server* instructions.

# use existing key or generate a new one according to docs:
# https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent
# add public key as a deployment key to the repo.

# Create SSH secret as described in: https://fluxcd.io/docs/components/source/gitrepositories/#ssh-authentication
# `k get secret flux-system -n flux-system` is the secret in the link above (ssh-credentials)


flux bootstrap git \
  --url=ssh://git@github.com/olga-mir/playground \
  --branch=main \
  --private-key-file=$HOME/.ssh/flux-github-key-2 \
  --path=clusters/cluster-0
