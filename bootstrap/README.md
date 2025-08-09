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
│   ├── crossplane/          # Crossplane configs that run ON KIND
│   │   ├── base/            # Providers, compositions, XRDs for kind
│   │   ├── composite-resources/  # Control-plane & apps-dev cluster definitions
│   │   ├── providerconfigs/ # Provider configurations
│   │   └── secrets/         # GCP credentials and secrets
│   ├── flux/                # Flux configuration for kind cluster
│   └── kind-config.yaml     # Kind cluster specification
└── README.md               # This file
```

## 3-Tier Architecture

1. **Kind cluster** (bootstrap) → provisions **control-plane cluster**
   - Uses Crossplane configs in `bootstrap/kind/crossplane/`
   - Provisions GKE control-plane cluster via `control-plane-composition`

2. **Control-plane cluster** → provisions **workload clusters** 
   - Uses Crossplane configs in `control-plane-crossplane/`
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

- **`bootstrap/kind/crossplane/`** = Crossplane configs that **run on kind** 
- **`control-plane-crossplane/`** = Crossplane configs that **run on control-plane**