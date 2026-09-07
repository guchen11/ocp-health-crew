# CNV-95003 Certainty Test Suite

Run on clod30 bastion (`aa37-h07-000-r740xd.rdu3.labs.perfscale.redhat.com`).

## Prerequisites

- `KUBECONFIG=/root/mno/kubeconfig`
- `source-ns/source-snapshot` ready (`setup-source.sh` if needed)
- `kube-burner` installed (test 2 only)
- `ceph-csi-controller-manager` scaled to **0** during the run (prevents operator reverting manual image swaps), restored to 1 at end

## Deploy

From laptop:

```bash
scp repro-cnv95003/lib-cnv95003.sh repro-cnv95003/run-certainty-suite.sh \
  root@aa37-h07-000-r740xd.rdu3.labs.perfscale.redhat.com:/root/repro-cnv95003/
ssh root@aa37-h07-000-r740xd.rdu3.labs.perfscale.redhat.com \
  'chmod +x /root/repro-cnv95003/lib-cnv95003.sh /root/repro-cnv95003/run-certainty-suite.sh'
```

## Run

```bash
ssh root@aa37-h07-000-r740xd.rdu3.labs.perfscale.redhat.com
export KUBECONFIG=/root/mno/kubeconfig
cd /root/repro-cnv95003

# Full suite (~2-3 hours)
./run-certainty-suite.sh

# Or individual tests
./run-certainty-suite.sh 1          # A/B/A PVC clone only (~20 min)
./run-certainty-suite.sh 2          # VM creation A/B/A (~90 min)
./run-certainty-suite.sh 3 4 5      # mechanism tests (~45 min)
```

## Tests

| # | Name | What it proves | Pass criteria |
|---|------|----------------|---------------|
| 1 | A/B/A PVC clone | Rollout gate fixed; reversible regression | baseline ~60s, swapped ~100s+, restored ~60s |
| 2 | VM creation A/B/A | Matches Purti's kube-burner methodology | swapped ~30-50% slower than baseline |
| 3 | Fresh snapshot | Rules out polluted Ceph state | same delta as test 1 |
| 4 | RBD features | Mechanism: image features on clones | 4.22 shows exclusive-lock, object-map, fast-diff |
| 5 | SC comparison | Virt SC hit harder than non-virt | larger delta on virt SC |

## Outputs

| File | Content |
|------|---------|
| `certainty-suite.log` | Timestamped run log |
| `certainty-suite-results.csv` | Structured results |
| `rbd-features-4.19-pvc*.txt` | RBD info per clone (test 4) |
| `kubeburner-*.log` | Per-phase kube-burner output (test 2) |

## After run

Cluster is restored to cephcsi 4.19 automatically.

Verify:

```bash
oc exec -n openshift-storage deploy/openshift-storage.rbd.csi.ceph.com-ctrlplugin \
  -c csi-rbdplugin -- cephcsi --version
```

## Claims unlocked

- After tests 1-2: *"Reproduced Purti's VM creation regression by swapping only ceph-csi on OCP 4.19."*
- After tests 4-5: *"Mechanism confirmed: 4.22 applies expensive image features to temp clones on virt SC."*
