"""Keyword and component maps for Jira-driven health check suggestions."""

# Keywords that indicate a bug might need a health check
HEALTH_CHECK_KEYWORDS = {
    "crash": "Pod crash detection",
    "oom": "OOM event monitoring",
    "memory leak": "Memory usage check",
    "high latency": "Latency monitoring",
    "not ready": "Readiness check",
    "stuck": "Stuck resource detection",
    "timeout": "Timeout detection",
    "certificate": "Certificate expiry check",
    "expir": "Expiration monitoring",
    "failed": "Failure detection",
    "degraded": "Degraded state check",
    "unavailable": "Availability check",
    "pending": "Pending resource check",
    "node not": "Node health check",
    "kubelet": "Kubelet health check",
    "etcd": "etcd health check",
    "migration": "Migration status check",
    "storage": "Storage health check",
    "pvc": "PVC status check",
    "csi": "CSI driver check",
    "operator": "Operator health check",
    "catalog": "Catalog source check",
    "router": "Router health check",
    "network": "Network connectivity check",
    "dns": "DNS resolution check",
    "api": "API server check",
}

# Components that map to health check categories
COMPONENT_TO_CHECK = {
    "Etcd": "etcd",
    "Machine Config Operator": "mco",
    "Networking": "network",
    "Storage": "storage",
    "OLM": "olm",
    "CNV": "cnv",
    "Virtualization": "cnv",
    "kube-apiserver": "apiserver",
    "oauth": "oauth",
    "Installer": "installer",
}
