global:
  image:
    tag: "${ARGOCD_VERSION}"

configs:
  params:
    server.insecure: true
  cm:
    kustomize.buildOptions: "--enable-helm"

    # Crossplane tracking annotations - enables better resource relationship tracking
    application.instanceLabelKey: argocd.argoproj.io/instance

    # Crossplane resource health checks
    resource.customizations: |
      # Crossplane Provider health check
      pkg.crossplane.io/Provider:
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Healthy" and condition.status == "True" then
                  health_status.status = "Healthy"
                  health_status.message = "Provider is healthy"
                  return health_status
                elseif condition.type == "Healthy" and condition.status == "False" then
                  health_status.status = "Degraded"
                  health_status.message = condition.reason or "Provider is not healthy"
                  return health_status
                end
              end
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for provider to be ready"
          return health_status

      # Crossplane Configuration health check
      pkg.crossplane.io/Configuration:
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Healthy" and condition.status == "True" then
                  health_status.status = "Healthy"
                  health_status.message = "Configuration is healthy"
                  return health_status
                elseif condition.type == "Healthy" and condition.status == "False" then
                  health_status.status = "Degraded"
                  health_status.message = condition.reason or "Configuration is not healthy"
                  return health_status
                end
              end
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for configuration to be ready"
          return health_status

      # Crossplane Composition health check
      apiextensions.crossplane.io/Composition:
        health.lua: |
          local health_status = {}
          health_status.status = "Healthy"
          health_status.message = "Composition is ready"
          return health_status

      # Crossplane CompositeResourceDefinition health check
      apiextensions.crossplane.io/CompositeResourceDefinition:
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Established" and condition.status == "True" then
                  health_status.status = "Healthy"
                  health_status.message = "XRD is established"
                  return health_status
                elseif condition.type == "Established" and condition.status == "False" then
                  health_status.status = "Degraded"
                  health_status.message = condition.reason or "XRD is not established"
                  return health_status
                end
              end
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for XRD to be established"
          return health_status

      # Crossplane EnvironmentConfig health check
      apiextensions.crossplane.io/EnvironmentConfig:
        health.lua: |
          -- EnvironmentConfigs are data holders. If they exist, they are considered healthy.
          local health_status = {}
          health_status.status = "Healthy"
          health_status.message = "EnvironmentConfig is present"
          return health_status

      # Generic Crossplane ProviderConfig health check for *.crossplane.io group
      # Covers kubernetes.crossplane.io/ProviderConfig and others in *.crossplane.io
      "*.crossplane.io/ProviderConfig":
        health.lua: |
          -- ProviderConfigs are generally healthy if they are configured.
          -- This check prioritizes Ready conditions if present, otherwise assumes configured if status exists.
          local health_status = {}
          if obj.status ~= nil then
            local has_definitive_condition = false
            if obj.status.conditions ~= nil then
              for _, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "False" then
                    health_status.status = "Degraded"
                    health_status.message = condition.reason or condition.message or "ProviderConfig not ready"
                    has_definitive_condition = true
                    break
                  elseif condition.status == "True" then
                    health_status.status = "Healthy"
                    if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                      health_status.message = "ProviderConfig is ready and in use by " .. obj.status.users .. " resource(s)."
                    else
                      health_status.message = "ProviderConfig is ready."
                    end
                    has_definitive_condition = true
                    break
                  end
                end
              end
            end

            if not has_definitive_condition then
              -- No definitive Ready:True or Ready:False condition found.
              -- Fallback: if status exists, it's generally considered configured/healthy.
              health_status.status = "Healthy"
              if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                health_status.message = "ProviderConfig is configured and in use by " .. obj.status.users .. " resource(s)."
              else
                health_status.message = "ProviderConfig is configured."
              end
            end
          else
            health_status.status = "Progressing"
            health_status.message = "Waiting for ProviderConfig status."
          end
          return health_status

      # Specific Crossplane ProviderConfig health check for gcp.upbound.io
      gcp.upbound.io/ProviderConfig:
        health.lua: |
          -- ProviderConfigs are generally healthy if they are configured.
          -- This check prioritizes Ready conditions if present, otherwise assumes configured if status exists.
          local health_status = {}
          if obj.status ~= nil then
            local has_definitive_condition = false
            if obj.status.conditions ~= nil then
              for _, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "False" then
                    health_status.status = "Degraded"
                    health_status.message = condition.reason or condition.message or "ProviderConfig not ready"
                    has_definitive_condition = true
                    break
                  elseif condition.status == "True" then
                    health_status.status = "Healthy"
                    if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                      health_status.message = "ProviderConfig is ready and in use by " .. obj.status.users .. " resource(s)."
                    else
                      health_status.message = "ProviderConfig is ready."
                    end
                    has_definitive_condition = true
                    break
                  end
                end
              end
            end

            if not has_definitive_condition then
              health_status.status = "Healthy"
              if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                health_status.message = "ProviderConfig is configured and in use by " .. obj.status.users .. " resource(s)."
              else
                health_status.message = "ProviderConfig is configured."
              end
            end
          else
            health_status.status = "Progressing"
            health_status.message = "Waiting for ProviderConfig status."
          end
          return health_status

      # Generic Crossplane ProviderConfig health check for *.upbound.io group
      # Covers gcp.upbound.io/ProviderConfig, github.upbound.io/ProviderConfig, aws.upbound.io/ProviderConfig etc.
      "*.upbound.io/ProviderConfig":
        health.lua: |
          -- ProviderConfigs are generally healthy if they are configured.
          -- This check prioritizes Ready conditions if present, otherwise assumes configured if status exists.
          local health_status = {}
          if obj.status ~= nil then
            local has_definitive_condition = false
            if obj.status.conditions ~= nil then
              for _, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "False" then
                    health_status.status = "Degraded"
                    health_status.message = condition.reason or condition.message or "ProviderConfig not ready"
                    has_definitive_condition = true
                    break
                  elseif condition.status == "True" then
                    health_status.status = "Healthy"
                    if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                      health_status.message = "ProviderConfig is ready and in use by " .. obj.status.users .. " resource(s)."
                    else
                      health_status.message = "ProviderConfig is ready."
                    end
                    has_definitive_condition = true
                    break
                  end
                end
              end
            end

            if not has_definitive_condition then
              -- No definitive Ready:True or Ready:False condition found.
              -- Fallback: if status exists, it's generally considered configured/healthy.
              health_status.status = "Healthy"
              if obj.status.users ~= nil and tonumber(obj.status.users) >= 0 then
                health_status.message = "ProviderConfig is configured and in use by " .. obj.status.users .. " resource(s)."
              else
                health_status.message = "ProviderConfig is configured."
              end
            end
          else
            health_status.status = "Progressing"
            health_status.message = "Waiting for ProviderConfig status."
          end
          return health_status

      # Crossplane ProviderConfigUsage (e.g., for GitHub provider)
      github.upbound.io/ProviderConfigUsage:
        health.lua: |
          -- ProviderConfigUsage resources are link objects.
          -- If they exist, they are considered healthy.
          local health_status = {}
          health_status.status = "Healthy"
          health_status.message = "ProviderConfigUsage link exists"
          return health_status

      # Generic Crossplane Composite Resource health check (applies to all XRDs)
      "*.crossplane.io/*":
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              local ready = false
              local synced = false
              local error_message = ""

              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "True" then
                    ready = true
                  else
                    error_message = condition.reason or condition.message or "Resource not ready"
                  end
                elseif condition.type == "Synced" then
                  if condition.status == "True" then
                    synced = true
                  else
                    error_message = condition.reason or condition.message or "Resource not synced"
                  end
                end
              end

              if ready and synced then
                health_status.status = "Healthy"
                health_status.message = "Resource is ready and synced"
              elseif not synced then
                health_status.status = "Degraded"
                health_status.message = "Sync failed: " .. error_message
              else
                health_status.status = "Progressing"
                health_status.message = "Resource is syncing: " .. error_message
              end
              return health_status
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for resource status"
          return health_status

      # Managed Resources (MRs) - provider-specific resources
      "*.upbound.io/*":
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              local ready = false
              local synced = false
              local error_message = ""

              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "True" then
                    ready = true
                  else
                    error_message = condition.reason or condition.message or "Resource not ready"
                  end
                elseif condition.type == "Synced" then
                  if condition.status == "True" then
                    synced = true
                  else
                    error_message = condition.reason or condition.message or "Resource not synced"
                  end
                end
              end

              if ready and synced then
                health_status.status = "Healthy"
                health_status.message = "Managed resource is ready"
              elseif not synced then
                health_status.status = "Degraded"
                health_status.message = "Sync failed: " .. error_message
              else
                health_status.status = "Progressing"
                health_status.message = "Resource syncing: " .. error_message
              end
              return health_status
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for managed resource status"
          return health_status

      "*.gcp.upbound.io/*":
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              local ready = false
              local synced = false
              local error_message = ""

              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Ready" then
                  if condition.status == "True" then
                    ready = true
                  else
                    error_message = condition.reason or condition.message or "Resource not ready"
                  end
                elseif condition.type == "Synced" then
                  if condition.status == "True" then
                    synced = true
                  else
                    error_message = condition.reason or condition.message or "Resource not synced"
                  end
                end
              end

              if ready and synced then
                health_status.status = "Healthy"
                health_status.message = "GCP resource is ready"
              elseif not synced then
                health_status.status = "Degraded"
                health_status.message = "Sync failed: " .. error_message
              else
                health_status.status = "Progressing"
                health_status.message = "GCP resource syncing: " .. error_message
              end
              return health_status
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for GCP resource status"
          return health_status

      pkg.crossplane.io/Function:
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              local healthy = false
              local installed = false
              local error_message = ""

              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Healthy" then
                  if condition.status == "True" then
                    healthy = true
                  else
                    error_message = condition.reason or condition.message or "Function not healthy"
                  end
                elseif condition.type == "Installed" then
                  if condition.status == "True" then
                    installed = true
                  else
                    error_message = condition.reason or condition.message or "Function not installed"
                  end
                end
              end

              if healthy and installed then
                health_status.status = "Healthy"
                health_status.message = "Function is healthy and installed"
              elseif not installed then
                health_status.status = "Degraded"
                health_status.message = "Installation failed: " .. error_message
              elseif not healthy then
                health_status.status = "Degraded"
                health_status.message = "Health check failed: " .. error_message
              else
                health_status.status = "Progressing"
                health_status.message = "Function is installing: " .. error_message
              end
              return health_status
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for function status"
          return health_status

      pkg.crossplane.io/ProviderRevision:
        health.lua: |
          local health_status = {}
          if obj.status ~= nil then
            if obj.status.conditions ~= nil then
              for i, condition in ipairs(obj.status.conditions) do
                if condition.type == "Healthy" and condition.status == "True" then
                  health_status.status = "Healthy"
                  health_status.message = "ProviderRevision is healthy"
                  return health_status
                elseif condition.type == "Healthy" and condition.status == "False" then
                  health_status.status = "Degraded"
                  health_status.message = condition.reason or "ProviderRevision is not healthy"
                  return health_status
                end
              end
            end
          end
          health_status.status = "Progressing"
          health_status.message = "Waiting for ProviderRevision to be ready"
          return health_status

    # Increase timeouts for slow Crossplane resources
    timeout.reconciliation: 300s
    timeout.hard.reconciliation: 600s

    # Enable resource tracking for better composite resource visibility
    resource.trackingMethod: annotation

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

  # Increase controller timeout for better Crossplane resource handling
  env:
    - name: ARGOCD_RECONCILIATION_TIMEOUT
      value: "600s"
