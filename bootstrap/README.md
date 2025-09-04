# Bootstrap Directory

This directory contains everything needed to bootstrap the 3-tier cluster architecture.

## Structure

```
bootstrap/
├── scripts/                 # Bootstrap scripts
│   ├── 00-cleanup.sh        # Cleanup all infrastructure
│   ├── 01-once-gcp-resources-setup.sh  # One-time GCP setup
│   ├── 02-create-and-setup-kind.sh     # Create kind cluster
│   └── 03-apply-compositions.sh        # Apply Crossplane configs to kind
├── kind/                    # Kind cluster configuration
│   ├── crossplane/          # Crossplane cluster definitions that run ON KIND
│   │   └── clusters/        # Control-plane cluster definition
│   ├── flux/                # Flux configuration for kind cluster
│   │   ├── install/         # Crossplane installation
│   │   ├── providers/       # Crossplane providers
│   │   ├── functions/       # Crossplane functions
│   │   ├── compositions/    # Crossplane compositions and XRDs
│   │   └── providerconfigs/ # Provider configurations
│   └── kind-config.yaml     # Kind cluster specification
└── README.md               # This file
```

## 3-Tier Architecture

1. **Kind cluster** (bootstrap) → provisions **control-plane cluster**
   - Uses Crossplane setup in `bootstrap/kind/flux/` (managed by Flux)
   - Uses cluster definitions in `bootstrap/kind/crossplane/clusters/`
   - Provisions GKE control-plane cluster via `gke-cluster-composition`

2. **Control-plane cluster** → provisions **workload clusters** 
   - Uses Crossplane configs in `bootstrap/control-plane/crossplane/`
   - Provisions workload clusters via `workload-cluster-composition`

3. **Workload clusters** → run applications
   - Managed by control-plane's Crossplane
   - Applications deployed via Flux

## Usage

Run the bootstrap process:
```bash
task setup:deploy
```

This executes:
1. `02-create-and-setup-kind.sh` - Creates kind cluster with Crossplane + Flux
2. `03-apply-compositions.sh` - Provisions control-plane cluster via Crossplane

## Key Distinction

- **`bootstrap/kind/flux/`** = Crossplane setup (providers, compositions) managed by Flux on kind
- **`bootstrap/kind/crossplane/`** = Cluster definitions provisioned by Crossplane on kind
- **`bootstrap/control-plane/crossplane/`** = Crossplane configs that **run on control-plane**