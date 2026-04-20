# Current Mission: Validation Loop

We are currently running a validation loop. The system is fully operational, and the codebase has been completely migrated to Crossplane v2 (using namespace-scoped managed resources exclusively).

**Key assumptions for this run:**
- Everything works as expected. This run is strictly a test to validate that the cluster provisioning and GitOps reconciliation loop complete successfully.
- Do not assume that errors indicate a fundamental architectural issue unless repeatedly proven otherwise.
- We have completely moved to Crossplane v2. Ignore any cluster-scoped managed resources (e.g., `*.upbound.io` where namespaced is false) and only interact with namespace-scoped managed resources (e.g., `*.m.upbound.io`).
- Be aware of naming collisions: when querying `providers`, always use the fully qualified name `providers.pkg.crossplane.io` for Crossplane providers, as `providers` alone may resolve to Flux notification providers (`providers.notification.toolkit.fluxcd.io`).
- Similarly, use fully qualified names for managed resources (e.g., `clusters.container.gcp.m.upbound.io`) instead of short names to avoid ambiguity.
