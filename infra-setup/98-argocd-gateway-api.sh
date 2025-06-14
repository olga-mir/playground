#!/bin/bash
# Gateway Setup Script with DNS Update
# This script sets up Gateway API resources for ArgoCD and updates DNS in a different project

# Set your environment variables
NAMESPACE="argocd"
GATEWAY_NAME="argocd-gateway"
HTTPROUTE_NAME="argocd-route"
TTL=300

# Record timestamp for logging
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
echo "[${TIMESTAMP}] Starting Gateway API setup for ArgoCD..."

# 1. Check if certificate exists, create if not
echo "Checking for SSL certificate..."
CERT_EXISTS=$(gcloud compute ssl-certificates list --filter="name=${CERT_NAME}" --format="value(name)" 2>/dev/null)
if [ -z "$CERT_EXISTS" ]; then
  echo "Creating Google-managed SSL certificate..."
  gcloud compute ssl-certificates create ${CERT_NAME} \
    --domains=${DOMAIN} \
    --global
  echo "Certificate creation initiated. Note that provisioning may take 5-15 minutes."
else
  echo "Certificate ${CERT_NAME} already exists."
fi

# 2. Create Gateway resource with SSL certificate
echo "Creating Gateway resource..."
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: ${GATEWAY_NAME}
  namespace: ${NAMESPACE}
spec:
  gatewayClassName: gke-l7-global-external-managed
  listeners:
    - name: http
      port: 80
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
    - name: https
      port: 443
      protocol: HTTPS
      allowedRoutes:
        namespaces:
          from: Same
      tls:
        mode: Terminate
        options:
          networking.gke.io/pre-shared-certs: ${CERT_NAME}
EOF

# 3. Create HTTPRoute
echo "Creating HTTPRoute resource..."
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ${HTTPROUTE_NAME}
  namespace: ${NAMESPACE}
spec:
  hostnames:
    - "${DOMAIN}"
  parentRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: ${GATEWAY_NAME}
      namespace: ${NAMESPACE}
  rules:
    - backendRefs:
        - group: ""
          kind: Service
          name: argocd-server
          port: 80
          weight: 1
      matches:
        - path:
            type: PathPrefix
            value: /
EOF

# 4. Wait for Gateway to get an IP address
echo "Waiting for Gateway to be assigned an IP address..."
ATTEMPTS=0
MAX_ATTEMPTS=20
while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
  EXTERNAL_IP=$(kubectl get gateway ${GATEWAY_NAME} -n ${NAMESPACE} -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
  if [ ! -z "$EXTERNAL_IP" ]; then
    echo "✅ Gateway assigned IP address: ${EXTERNAL_IP}"
    break
  fi
  ATTEMPTS=$((ATTEMPTS+1))
  echo "Attempt ${ATTEMPTS}/${MAX_ATTEMPTS}. Waiting 15 seconds..."
  sleep 15
done

if [ -z "$EXTERNAL_IP" ]; then
  echo "❌ Failed to get IP address for Gateway. Please check Gateway status manually."
  exit 1
fi

# 5. Update DNS A record in the different project
echo "Updating DNS A record in project ${DNS_PROJECT}..."
gcloud dns record-sets update ${DOMAIN}. \
  --type=A \
  --zone=${DNS_ZONE} \
  --rrdatas=${EXTERNAL_IP} \
  --ttl=${TTL} \
  --project=${DNS_PROJECT}

# 6. Verify DNS record update
echo "Verifying DNS record update..."
gcloud dns record-sets list \
  --zone=${DNS_ZONE} \
  --name=${DOMAIN}. \
  --type=A \
  --project=${DNS_PROJECT}

echo "[${TIMESTAMP}] Setup completed. ArgoCD should be accessible at:"
echo "  * HTTP:  http://${DOMAIN}"
echo "  * HTTPS: https://${DOMAIN} (once certificate is fully provisioned)"
echo ""
echo "Note: Certificate provisioning can take 5-15 minutes. Use the following command to check status:"
echo "gcloud compute ssl-certificates describe ${CERT_NAME} --format=\"json(name,managed.status)\""
