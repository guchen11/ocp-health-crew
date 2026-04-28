"""Expandable health check cards grid for HTML report."""


def _render_health_checks_panel(data):
    total_nodes = len(data['nodes']['healthy']) + len(data['nodes']['unhealthy'])
    healthy_nodes = len(data['nodes']['healthy'])
    total_ops = len(data['operators']['healthy']) + len(data['operators']['degraded']) + len(data['operators']['unavailable'])
    healthy_ops = len(data['operators']['healthy'])
    unhealthy_pods = len(data['pods']['unhealthy'])
    return f'''    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">🧪 Health Check Results <span style="font-size:10px;color:var(--text-secondary);font-weight:400;margin-left:auto;">Click a check to see the command &amp; what it validates</span></div>
        <div class="check-grid">
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🖥️</span>
                    <div class="check-info">
                        <div class="check-name">Nodes</div>
                        <div class="check-result">{healthy_nodes}/{total_nodes} Ready</div>
                    </div>
                    <span class="check-status">{'✅' if not data['nodes']['unhealthy'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get nodes --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>All nodes must show 'Ready' status. Flags any node that is NotReady, SchedulingDisabled, or Unknown.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">⚙️</span>
                    <div class="check-info">
                        <div class="check-name">Cluster Operators</div>
                        <div class="check-result">{healthy_ops}/{total_ops} Available</div>
                    </div>
                    <span class="check-status">{'✅' if not data['operators']['degraded'] and not data['operators']['unavailable'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get co --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Every operator must have AVAILABLE=True and DEGRADED=False. Flags operators that are unavailable or degraded.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">📦</span>
                    <div class="check-info">
                        <div class="check-name">Pods</div>
                        <div class="check-result">{data['pods']['healthy']} Running, {unhealthy_pods} Unhealthy</div>
                    </div>
                    <span class="check-status">{'✅' if not data['pods']['unhealthy'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get pods -A --no-headers --field-selector=status.phase!=Running,status.phase!=Succeeded</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Lists pods NOT in Running or Succeeded state (CrashLoopBackOff, Pending, Error, Unknown, ImagePullBackOff).</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">💻</span>
                    <div class="check-info">
                        <div class="check-name">KubeVirt</div>
                        <div class="check-result">{data['kubevirt']['status'] if data['kubevirt']['installed'] else 'Not installed'}, {data['kubevirt']['vms_running']} VMs</div>
                    </div>
                    <span class="check-status">{'✅' if data['kubevirt']['status'] == 'Deployed' and not data['kubevirt']['failed_vmis'] else '⚠️' if data['kubevirt']['installed'] else '➖'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation commands</div>
                    <code>oc get kubevirt -A --no-headers
oc get vmi -A --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>KubeVirt CR must show 'Deployed' phase. Counts running VMs and identifies failed/stuck VMIs.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">📊</span>
                    <div class="check-info">
                        <div class="check-name">Resource Usage</div>
                        <div class="check-result">{len(data['resources']['high_cpu'])} high CPU, {len(data['resources']['high_memory'])} high mem</div>
                    </div>
                    <span class="check-status">{'✅' if not data['resources']['high_cpu'] and not data['resources']['high_memory'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc adm top nodes --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Shows CPU/memory usage per node. Flags nodes above threshold (default: CPU >85%, Memory >80%).</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🗄️</span>
                    <div class="check-info">
                        <div class="check-name">etcd Health</div>
                        <div class="check-result">{data['etcd']['healthy']} members healthy</div>
                    </div>
                    <span class="check-status">{'✅' if not data['etcd']['unhealthy'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation commands</div>
                    <code>oc get pods -n openshift-etcd -l app=etcd --no-headers
oc rsh -n openshift-etcd -c etcdctl &lt;etcd-pod&gt; etcdctl endpoint status --cluster -w table</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>All etcd member pods must be Running. Checks cluster-wide endpoint health, leader election, DB size, and raft index lag.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">💾</span>
                    <div class="check-info">
                        <div class="check-name">PVC Status</div>
                        <div class="check-result">{len(data['pvcs']['pending'])} pending</div>
                    </div>
                    <span class="check-status">{'✅' if not data['pvcs']['pending'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get pvc -A --no-headers | grep -v Bound</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>All PVCs should be Bound. Pending PVCs indicate storage provisioning failure or missing StorageClass.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🔄</span>
                    <div class="check-info">
                        <div class="check-name">VM Migrations</div>
                        <div class="check-result">{data['migrations']['running']} running, {len(data['migrations']['failed']) + data['migrations']['failed_count']} failed</div>
                    </div>
                    <span class="check-status">{'✅' if not data['migrations']['failed'] and data['migrations']['failed_count'] == 0 else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation commands</div>
                    <code>oc get vmim -A --no-headers | grep -v Succeeded
oc get vmim -A -o json | grep '"phase":"Failed"' | wc -l</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Lists active/pending/failed migrations. Only 'Succeeded' is healthy. High failure count suggests underlying storage/network issues.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">💥</span>
                    <div class="check-info">
                        <div class="check-name">OOM Events</div>
                        <div class="check-result">{len(data['oom_events'])} recent events</div>
                    </div>
                    <span class="check-status">{'✅' if not data['oom_events'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get events -A --field-selector reason=OOMKilled --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Lists recent OOMKilled events across all namespaces. OOM events indicate pods running out of memory limits.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🔌</span>
                    <div class="check-info">
                        <div class="check-name">CSI Drivers</div>
                        <div class="check-result">{len(data['csi_issues'])} issues</div>
                    </div>
                    <span class="check-status">{'✅' if not data['csi_issues'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get pods -A --no-headers | grep -E 'csi|driver' | grep -v Running</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>CSI driver pods must be Running. Down CSI drivers mean storage operations will fail.</div>
                </div>
            </div>
            
            <div class="check-section-title">CNV / KubeVirt Checks</div>
            
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🔧</span>
                    <div class="check-info">
                        <div class="check-name">virt-handler</div>
                        <div class="check-result">{data['virt_handler']['healthy']} healthy, {len(data['virt_handler']['high_memory'])} high mem</div>
                    </div>
                    <span class="check-status">{'✅' if not data['virt_handler']['unhealthy'] and not data['virt_handler']['high_memory'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation commands</div>
                    <code>oc get pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers
oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>All virt-handler DaemonSet pods must be Running. Checks memory/CPU usage -- high memory (>500Mi) indicates possible leak (CNV-66551).</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🎛️</span>
                    <div class="check-info">
                        <div class="check-name">virt-controller/api</div>
                        <div class="check-result">{data['virt_ctrl']['healthy']} healthy</div>
                    </div>
                    <span class="check-status">{'✅' if not data['virt_ctrl']['unhealthy'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get pods -n openshift-cnv -l 'kubevirt.io in (virt-controller,virt-api)' --no-headers</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>virt-controller and virt-api pods must be Running. These are the CNV control plane components.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🚀</span>
                    <div class="check-info">
                        <div class="check-name">virt-launcher</div>
                        <div class="check-result">{len(data['virt_launcher_bad'])} unhealthy</div>
                    </div>
                    <span class="check-status">{'✅' if not data['virt_launcher_bad'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get pods -A -l kubevirt.io=virt-launcher --no-headers | grep -v Running</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Finds virt-launcher pods not Running. Each VM has a launcher pod -- unhealthy launcher = VM problem.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">💿</span>
                    <div class="check-info">
                        <div class="check-name">DataVolumes</div>
                        <div class="check-result">{len(data['dv_issues'])} stuck/pending</div>
                    </div>
                    <span class="check-status">{'✅' if not data['dv_issues'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get dv -A --no-headers | grep -vE 'Succeeded|PVCBound'</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>DataVolumes should be Succeeded or PVCBound. Stuck DVs indicate import/clone failures.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">📸</span>
                    <div class="check-info">
                        <div class="check-name">VolumeSnapshots</div>
                        <div class="check-result">{len(data['snapshot_issues'])} not ready</div>
                    </div>
                    <span class="check-status">{'✅' if not data['snapshot_issues'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get volumesnapshot -A --no-headers | grep -v 'true'</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Volume snapshots should show readyToUse=true. Unready snapshots indicate backup/clone problems.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">🚧</span>
                    <div class="check-info">
                        <div class="check-name">Cordoned VMs</div>
                        <div class="check-result">{len(data['cordoned_vms'])} VMs at risk</div>
                    </div>
                    <span class="check-status">{'✅' if not data['cordoned_vms'] else '❌'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation commands</div>
                    <code>oc get nodes --no-headers | grep SchedulingDisabled
oc get vmi -A -o wide --no-headers | grep &lt;cordoned-node&gt;</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Finds cordoned/drained nodes and identifies VMs running on them. These VMs are at risk during maintenance.</div>
                </div>
            </div>
            <div class="check-card">
                <div class="check-card-row">
                    <span class="check-icon">⏳</span>
                    <div class="check-info">
                        <div class="check-name">Stuck Migrations</div>
                        <div class="check-result">{len(data['stuck_migrations'])} running/stuck</div>
                    </div>
                    <span class="check-status">{'✅' if not data['stuck_migrations'] else '⚠️'}</span>
                    <span class="check-expand">▼</span>
                </div>
                <div class="check-cmd">
                    <div class="check-cmd-label">Validation command</div>
                    <code>oc get vmim -A --no-headers | grep Running</code>
                    <div class="check-validates"><div class="check-validates-label">What it checks</div>Finds migrations stuck in Running state. Long-running migrations may be hung due to network/storage issues.</div>
                </div>
            </div>
        </div>
    </div>
'''
