#!/usr/bin/env bash
# gke-context.sh
# Shared helper for resolving GKE kubeconfig contexts by short cluster name.
# GKE context names embed the project ID (gke_<project>_<zone>_<cluster>) —
# discover them from kubeconfig by suffix pattern so callers stay project-ID-agnostic.
#
# Usage: source this file, then call `gke_ctx control-plane` or `gke_ctx apps-dev`.

gke_ctx() { kubectl config get-contexts -o name 2>/dev/null | grep "_${1}$" | head -1 || true; }
