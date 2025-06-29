We continue working in `infra-setup` folder to migrate local kind installation from bash to GitOpss powered by Flux.
We have a working installation of FluxCD on `kind` cluster.
Now we need to migrate "kubectl apply" from scripts found in this folder to Flux.
Note that there are some manifests that have sensitive or semi-sensitive information, make sure these are not committed to repo
Use Flux mechanisms to pass these values around without committing to repo.
Don't aim for a full solution, it is ok if we still have a lot of bash code to setup config and credentials
You can experiment with current kind cluster, but make sure that all changes need to be captured in manifests and scripts. This must be a reproducible setup
