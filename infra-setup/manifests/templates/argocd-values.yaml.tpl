global:
  image:
    tag: "${ARGOCD_VERSION}"

configs:
  params:
    server.insecure: true
  cm:
    kustomize.buildOptions: "--enable-helm"
    cluster.apps-dev-cluster: |
      name: ${target_cluster_name}
      server: ${SERVER}
      config:
        tlsClientConfig:
          insecure: false
          caData: ${CERTIFICATE_AUTHORITY_DATA}
        bearerToken: ${TOKEN}

repoServer:
  podSecurityContext:
    runAsNonRoot: true
    fsGroup: 999
    runAsUser: 999

  extraContainers:
    - name: env-substitution-plugin
      command: ["/var/run/argocd/argocd-cmp-server"]
      image: quay.io/argoproj/argocd:latest
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
      volumeMounts:
        - mountPath: /var/run/argocd
          name: var-files
        - mountPath: /home/argocd/cmp-server/config
          name: plugin-config
        - mountPath: /home/argocd/cmp-server/plugins
          name: plugins
        - mountPath: /tmp
          name: cmp-tmp

  volumes:
    - emptyDir: {}
      name: cmp-tmp
    - configMap:
        name: argocd-envsubst-plugin
      name: plugin-config

  resources:
    requests:
      cpu: "250m"
      memory: "1Gi"
    limits:
      memory: "2Gi"

applicationSet:
  enabled: true
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      memory: "2Gi"

server:
  resources:
    requests:
      cpu: "1000m"
      memory: "2Gi"
    limits:
      memory: "3Gi"
  replicas: 2

controller:
  resources:
    requests:
      cpu: "700m"
      memory: "2Gi"
    limits:
      memory: "3Gi"
