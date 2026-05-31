#!/usr/bin/env bash
# bootstrap.sh — Installs platform dependencies into the kind cluster.
# Usage: ./infra/kind/bootstrap.sh
#
# Prerequisites: kind, kubectl, helm, docker running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLUSTER_NAME="astraeus-local"

echo "==> Checking prerequisites..."
for cmd in kind kubectl helm docker; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is not installed." >&2
    exit 1
  fi
done

# Create cluster if it doesn't exist
if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  echo "==> Creating kind cluster: ${CLUSTER_NAME}"
  kind create cluster --config "$SCRIPT_DIR/cluster.yaml"
else
  echo "==> Cluster ${CLUSTER_NAME} already exists, reusing."
fi

# Set kubectl context
kubectl cluster-info --context "kind-${CLUSTER_NAME}"

echo "==> Creating namespaces..."
for ns in ingress platform data streaming research trading agents web observability argocd; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done

echo "==> Installing NGINX Ingress Controller..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress \
  --set controller.hostPort.enabled=true \
  --set controller.service.type=NodePort \
  --set controller.watchIngressWithoutClass=true \
  --wait --timeout 120s

echo "==> Installing ArgoCD..."
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --set server.service.type=NodePort \
  --set server.extraArgs="{--insecure}" \
  --set configs.params."server\.insecure"=true \
  --wait --timeout 180s

echo "==> Installing Prometheus + Grafana (kube-prometheus-stack)..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update
helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --set grafana.service.type=NodePort \
  --set grafana.service.nodePort=30000 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --wait --timeout 300s

echo "==> Installing Argo Rollouts..."
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm upgrade --install argo-rollouts argo/argo-rollouts \
  --namespace argocd \
  --set dashboard.enabled=true \
  --wait --timeout 120s

echo "==> Applying default-deny NetworkPolicies..."
for ns in research trading agents web; do
  kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: $ns
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
EOF
done

echo "==> Bootstrap complete!"
echo ""
echo "  ArgoCD UI:   http://localhost:8080 (port-forward: kubectl port-forward svc/argocd-server -n argocd 8080:443)"
echo "  Grafana:     http://localhost:30000 (admin/prom-operator)"
echo "  ArgoCD pass: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
echo ""
