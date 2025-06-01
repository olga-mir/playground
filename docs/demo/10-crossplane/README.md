# Crossplane Demo

![crossplane-intro](../images/crossplane-intro.png)

# This page is WIP


## On Management Cluster

```
% k get apps -A
NAMESPACE   NAME                              SYNC STATUS   HEALTH STATUS
argocd      crossplane-compositions           Synced        Healthy
argocd      crossplane-environment-configs    Synced        Healthy
argocd      crossplane-functions              Synced        Healthy
argocd      crossplane-provider-configs       Synced        Healthy
argocd      crossplane-providers              Synced        Healthy
argocd      crossplane-xrd                    Synced        Healthy
argocd      kagent-crds                       Synced        Healthy
argocd      kagent-rendered-helm-workaround   Synced        Healthy
argocd      kgateway                          Synced        Healthy
argocd      kgateway-crds                     Synced        Healthy
argocd      mcp-gateway-config                Synced        Healthy
argocd      team-alpha-tenant                 Synced        Healthy
% k get appset -A
NAMESPACE   NAME                              AGE
argocd      helm-applications                 17m
argocd      platform-applications-directory   17m
argocd      platform-applications-plugin      17m
argocd      teams-tenancies                   17m
%
% k get providers -A
NAME                                     INSTALLED   HEALTHY   PACKAGE                                                             AGE
crossplane-contrib-provider-family-gcp   True        True      xpkg.crossplane.io/crossplane-contrib/provider-family-gcp:v1.13.0   14m
provider-gcp-iam                         True        True      xpkg.upbound.io/crossplane-contrib/provider-gcp-iam:v1.12.1         14m
provider-gcp-storage                     True        True      xpkg.upbound.io/crossplane-contrib/provider-gcp-storage:v1.12.1     14m
provider-kubernetes                      True        True      xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.9.0       14m
provider-upjet-github                    True        True      xpkg.upbound.io/crossplane-contrib/provider-upjet-github:v0.18.0    14m
%
% k get managed
NAME                                                            KIND             PROVIDERCONFIG                     SYNCED   READY   AGE
object.kubernetes.crossplane.io/team-alpha-landing-zone-mxphx   NetworkPolicy    kubernetes-provider-apps-cluster   True     True    12m
object.kubernetes.crossplane.io/team-alpha-landing-zone-p6wxp   Namespace        kubernetes-provider-apps-cluster   True     True    12m
object.kubernetes.crossplane.io/team-alpha-landing-zone-rwzx9   NetworkPolicy    kubernetes-provider-apps-cluster   True     True    12m
object.kubernetes.crossplane.io/team-alpha-landing-zone-sblkr   ServiceAccount   kubernetes-provider-apps-cluster   True     True    12m

NAME                                                              SYNCED   READY   EXTERNAL-NAME            AGE
repository.repo.github.upbound.io/team-alpha-landing-zone-XXXXX   True     True    team-alpha-service-one   12m

NAME                                                                   SYNCED   READY   EXTERNAL-NAME                                                                                                                                                                                                                                   AGE
bucketiammember.storage.gcp.upbound.io/team-alpha-landing-zone-XXXXXX  True     True    b/team-alpha-landing-zone-XXXXX/roles/storage.objectAdmin/principal://iam.googleapis.com/projects/XXXXXXXXXXXX/locations/global/workloadIdentityPools/XXXXXXXXXXX.svc.id.goog/subject/ns/team-alpha-service-one/sa/team-alpha-service-one-ksa   12m

NAME                                                          SYNCED   READY   EXTERNAL-NAME                   AGE
bucket.storage.gcp.upbound.io/team-alpha-landing-zone-XXXXXX  True     True    team-alpha-landing-zone-XXXXX   12m

NAME                                                                  SYNCED   READY   EXTERNAL-NAME                     AGE
teamrepository.team.github.upbound.io/team-alpha-landing-zone-nfxsq   True     True    12345678:team-alpha-service-one   12m

NAME                                                        SYNCED   READY   EXTERNAL-NAME   AGE
team.team.github.upbound.io/team-alpha-landing-zone-49pz5   True     True    12345679        12m
```

### On workload cluster

Example of network policy which is managed by Crossplane k8s provider installed on the management cluster.
Note that apps cluster does not run Crossplane at all.

```
% k get --show-managed-fields netpol proxy-egress -n team-alpha-service-one -o yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  annotations:
    kubectl.kubernetes.io/last-applied-configuration: '{"apiVersion":"networking.k8s.io/v1","kind":"NetworkPolicy","metadata":{"name":"proxy-egress","namespace":"team-alpha-service-one"},"spec":{"egress":[{"to":[{"ipBlock":{"cidr":"10.0.0.1/32"}}]}],"podSelector":{},"policyTypes":["Egress"]}}'
  creationTimestamp: "2025-06-01T08:50:15Z"
  generation: 1
  managedFields:
  - apiVersion: networking.k8s.io/v1
    fieldsType: FieldsV1
    fieldsV1:
      f:metadata:
        f:annotations:
          .: {}
          f:kubectl.kubernetes.io/last-applied-configuration: {}
      f:spec:
        f:egress: {}
        f:policyTypes: {}
    manager: crossplane-kubernetes-provider
    operation: Update
    time: "2025-06-01T08:50:15Z"
  name: proxy-egress
  namespace: team-alpha-service-one
  resourceVersion: "1748767815991983024"
  uid: ae8f840d-9ec6-4c7c-ad64-968a5a6d8306
spec:
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.0.1/32
  podSelector: {}
  policyTypes:
  - Egress
```
