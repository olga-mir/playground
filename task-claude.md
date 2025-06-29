The work is scoped mostly in infra-setup folder, maybe also Taskfiles
Install FluxCD on local kind cluster
Use latests and greatest version https://github.com/fluxcd/flux2/releases/tag/v2.6.3
Use personal token for bootstrap required variables available in
GITHUB_DEMO_REPO_OWNER
GITHUB_DEMO_REPO_NAME
GITHUB_FLUX_PLAYGROUND_PAT - PAT specifically for Flux due to its "elevated" perms

Your first task is to install and configure Flux and try to sync one manifest to validate that it works. Don't change everything right now.
