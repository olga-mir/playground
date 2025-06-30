apiVersion: gcp-beta.upbound.io/v1beta1
kind: ProviderConfig
metadata:
  name: crossplane-provider-gcp
spec:
  projectID: ${PROJECT_ID}
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: gcp-creds
      key: credentials