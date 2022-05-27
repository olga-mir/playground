# Using Flux to deploy Helm

```
infra
├── kong
│   ├── helm-release.yaml
│   ├── kustomization.yaml
│   └── namespace.yaml
├── kubefed
│   ├── helm-release.yaml
│   ├── kustomization.yaml
│   └── namespace.yaml
├── kustomization.yaml
└── sources
    ├── kong.yaml
    ├── kubefed.yaml
    └── kustomization.yaml
```

Status:

```
% flux get all
NAME                            REVISION        SUSPENDED       READY   MESSAGE
gitrepository/flux-system       main/0237f4b    False           True    stored artifact for revision 'main/0237f4b6c2b226fa648e79f80ea5fce5c716802c'

NAME                    REVISION                                                                SUSPENDED       READY   MESSAGE
helmrepository/kong     88d3b67840c3f22102541243a73a583b47d21ecbb49ec126ed1798d6eb393282        False           True    stored artifact for revision '88d3b67840c3f22102541243a73a583b47d21ecbb49ec126ed1798d6eb393282'
helmrepository/kubefed  4aebe12802a1d4cf3e81c3ea755fa6a45e63fcc06f6fbfdb0826b6c82be67265        False           True    stored artifact for revision '4aebe12802a1d4cf3e81c3ea755fa6a45e63fcc06f6fbfdb0826b6c82be67265'

NAME                            REVISION        SUSPENDED       READY   MESSAGE
helmchart/kong-kong             2.8.2           False           True    pulled 'kong' chart with version '2.8.2'
helmchart/kubefed-kubefed       0.9.2           False           True    pulled 'kubefed' chart with version '0.9.2'

NAME                            REVISION        SUSPENDED       READY   MESSAGE
kustomization/flux-system       main/0237f4b    False           True    Applied revision: main/0237f4b
kustomization/infrastructure    main/0237f4b    False           True    Applied revision: main/0237f4b
```

kong only partially running, because values were not supplied:
```
% k get helmrelease kong -o yaml | yq e '.status.conditions[1]' -                                                                                                                                                  main 7:27:12
lastTransitionTime: "2022-05-27T11:05:26Z"
message: |-
  Helm install failed: timed out waiting for the condition

  Last Helm logs:

  Clearing discovery cache
  beginning wait for 6 resources with timeout of 1m0s
  creating 8 resource(s)
  beginning wait for 8 resources with timeout of 5m0s
  Service does not have load balancer ingress IP address: kong/kong-kong-proxy
reason: InstallFailed
status: "False"
type: Released
```

