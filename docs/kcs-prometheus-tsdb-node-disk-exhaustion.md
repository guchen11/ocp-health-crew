# OpenShift: Prometheus TSDB fills worker node disk (DiskPressure / NotReady)

## Issue

- Worker nodes report **DiskPressure** or become **NotReady** with errors such as **no space left on device**.
- **`df`** or node diagnostics show the root filesystem (or `/var`) nearly full.
- Large consumption under **`/var/lib/kubelet/pods`** correlates with **`prometheus-k8s-*`** pods and volume **`prometheus-k8s-db`** (Prometheus time-series database).
- Core platform monitoring may show **Prometheus** pods unhealthy; other operators (for example **machine-config**, **network**, **DNS**) can degrade as a downstream effect of node disk or kubelet problems.

## Environment

- Red Hat OpenShift Container Platform 4.x with default or unbounded core **Prometheus** storage configuration.
- **Multi-node** clusters where platform Prometheus runs on **emptyDir**-backed storage (no **`volumeClaimTemplate`** in **`cluster-monitoring-config`**).
- **High metric cardinality** workloads (for example large **OpenShift Virtualization** / KubeVirt deployments with many VMs), short scrape intervals, or broad scrape coverage, often combined with default **15 day** time retention and no **`retentionSize`**.

## Root cause

By default, when persistent storage is not configured for platform Prometheus, TSDB data is stored on **local node storage** tied to the Prometheus pod (often **`emptyDir`** under kubelet). That data:

- Grows with **time** (default retention **15d**) and **ingest rate** (targets, labels, scrape frequency).
- Is **not** capped by **`retentionSize`** unless explicitly set.
- Shares the same disk space as the **host filesystem** used by the kubelet, container runtime, system logs, and other pods.

At sufficient scale, TSDB growth can **consume the node root disk**, triggering **DiskPressure**, **kubelet** instability, **NotReady** nodes, and cascade failures. **PVC-backed** Prometheus isolates TSDB to a dedicated volume and avoids exhausting the node OS disk for this workload.

## Resolution / preventive configuration

Red Hat recommends **persistent storage** for platform Prometheus and Alertmanager in production; on **multi-node** clusters, persistent storage is **required** for high availability. See **Monitoring stack for Red Hat OpenShift**: *Configuring core platform monitoring* → **Storing and recording data for core platform monitoring**.

### 1. Plan capacity

- Estimate **TSDB growth** (or provision conservatively large PVCs) when cardinality is high (for example many VMs and `kubevirt_*` metrics).
- Set **`retention`** and **`retentionSize`** so stored metrics stay within the PVC; leave headroom for WAL and compaction (documentation notes PV can fill temporarily around compaction; **`KubePersistentVolumeFillingUp`** may alert until space stabilizes).

### 2. Configure PVC and retention (`cluster-monitoring-config`)

Edit the **`ConfigMap`** **`cluster-monitoring-config`** in namespace **`openshift-monitoring`** and set **`prometheusK8s`** (and **`alertmanagerMain`** as needed) with **`volumeClaimTemplate`**, **`retention`**, and **`retentionSize`**.

Example pattern (replace storage class and sizes to match your environment):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    prometheusK8s:
      retention: 5d
      retentionSize: 250GB
      volumeClaimTemplate:
        spec:
          storageClassName: <your-storage-class>
          resources:
            requests:
              storage: 300Gi
    alertmanagerMain:
      volumeClaimTemplate:
        spec:
          storageClassName: <your-storage-class>
          resources:
            requests:
              storage: 5Gi
```

**Warning:** Updating PVC configuration **recreates** the affected **StatefulSet** and causes a **temporary monitoring outage**. Existing TSDB on **emptyDir** is **not** migrated; plan for **loss of historical metrics** on that store unless you use a separate backup or remote read/write strategy.

### 3. Verify

```bash
oc -n openshift-monitoring get pvc
oc -n openshift-monitoring get pods -l app.kubernetes.io/name=prometheus
oc -n openshift-monitoring exec -c prometheus prometheus-k8s-0 -- df -h /prometheus
oc -n openshift-monitoring get configmap cluster-monitoring-config -o yaml
```

Confirm Prometheus pods are **Running**, PVCs are **Bound**, and node **DiskPressure** clears after old local data is reclaimed (you may need **manual cleanup** of stale **`/var/lib/kubelet/pods`** directories if disks were 100% full and kubelet could not remove them; follow standard node disk troubleshooting).

### 4. Operational hardening

- Monitor **PVC utilization** and **node root filesystem** separately.
- For very high cardinality, consider **recording rules**, relabeling, or workload-specific tuning so ingest fits your retention and budget.
- Set cluster sizing and monitoring storage in **installation or day-2 runbooks** so defaults are not left in place on large clusters.

## Diagnostic steps (during an incident)

1. Identify full filesystem: **`df -h`** on the node (or **`oc debug node/...`** when healthy enough).
2. If **`/var/lib/kubelet/pods`** dominates usage, map large pod UIDs to pods: **`oc get pods -A -o wide`** and correlate with volume names (for example **`prometheus-k8s-db`**).
3. Confirm Prometheus storage mode: **`oc -n openshift-monitoring get configmap cluster-monitoring-config -o yaml`**
4. Check TSDB mount: **`oc -n openshift-monitoring exec -c prometheus prometheus-k8s-0 -- df -h /prometheus`**

## Workaround (emergency relief only)

Emergency relief (for example removing WAL/TSDB paths or force-deleting stuck pods) **risks data loss** and may require **manual cleanup** on nodes if disk was **100%** full. Prefer applying **PVC + retention limits** and freeing space in a controlled way. If **kubelet** certificates became stale after a long outage, approve pending **CSRs** after the node is stable enough to reconcile.

## Additional information

- [Monitoring stack for Red Hat OpenShift - Storing and recording data](https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/latest/html/configuring_core_platform_monitoring/storing-and-recording-data)
- Related node disk troubleshooting: see OpenShift documentation and existing Knowledgebase solutions for **disk pressure** and **ephemeral storage**.

## Article metadata (for publication)

| Field | Value |
|--------|--------|
| **Product** | Red Hat OpenShift Container Platform |
| **Component** | Monitoring / Cluster monitoring (Prometheus) |
| **Symptom** | Node DiskPressure / NotReady; full disk; Prometheus pod on node |
| **Cause** | Prometheus TSDB on local/emptyDir storage without byte cap at high ingest |
| **Fix** | `cluster-monitoring-config`: PVC + `retention` + `retentionSize`; node cleanup if needed |

---

*Internal draft: adapt titles, links, and product versions to match your Red Hat Solution/KCS template before external publication.*
