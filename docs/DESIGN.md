<p align="center">
  <img src="https://img.shields.io/badge/OpenShift-EE0000?style=for-the-badge&logo=redhatopenshift&logoColor=white" alt="OpenShift"/>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask"/>
  <img src="https://img.shields.io/badge/KubeVirt-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="KubeVirt"/>
  <img src="https://img.shields.io/badge/AI_Powered-FF6F00?style=for-the-badge&logo=tensorflow&logoColor=white" alt="AI"/>
</p>

<h1 align="center">🔍 CNV Health Crew</h1>

<p align="center">
  <strong>AI-Powered Performance Engineering & Health Monitoring for OpenShift + CNV</strong>
</p>

<p align="center">
  <em>🧠 Self-Evolving AI that Learns from Bugs, Emails & the Web</em>
</p>

<p align="center">
  <a href="#-key-innovations">Key Innovations</a> •
  <a href="#-features">Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-self-evolving-ai">Self-Evolving AI</a> •
  <a href="#-quick-start">Quick Start</a>
</p>

---

## 🚀 Key Innovations

<table>
<tr>
<td align="left" width="50%" style="background:linear-gradient(135deg,#4527a0,#311b92);color:white;padding:20px;">

### 🧠 Self-Evolving AI

**The system learns from multiple sources:**

- 🎫 **Jira Bugs** - Discovers new tests from bug reports
- 📧 **Email** - Learns from team discussions & alerts
- 🌐 **Web** - Searches docs, forums & knowledge bases
- 🎯 **Patterns** - Recognizes recurring issues
- ♾️ **Never stops** - Gets smarter with every run

</td>
<td align="left" width="50%" style="background:linear-gradient(135deg,#b71c1c,#880e4f);color:white;padding:20px;">

### ⚡ Performance Engineering

**Built for Performance Engineers:**

- 📊 **Resource profiling** - CPU, Memory, I/O per node
- 🔥 **Bottleneck detection** - Find hotspots instantly
- 📈 **Trend analysis** - Track performance over time
- ⚠️ **Threshold alerts** - Proactive warnings at 85%+
- 🎯 **Root cause analysis** - AI-powered deep investigation

</td>
</tr>
</table>

---

## 🔄 How the AI Evolves

<table>
<tr>
<td align="center" colspan="5" style="background:#1565c0;color:white;padding:15px;">
<h3>🧬 CONTINUOUS LEARNING CYCLE</h3>
<sub>The system automatically improves with every run</sub>
</td>
</tr>
<tr>
<td align="center" width="20%">
<h2>1️⃣</h2>
📥<br><strong>Gather Intel</strong><br>
<sub>🎫 Jira bugs<br>📧 Emails<br>🌐 Web docs</sub>
</td>
<td align="center" width="20%">
<h2>2️⃣</h2>
🔍<br><strong>Analyze</strong><br>
<sub>AI identifies patterns<br>& recurring issues</sub>
</td>
<td align="center" width="20%">
<h2>3️⃣</h2>
💡<br><strong>Suggest Tests</strong><br>
<sub>Proposes new health<br>checks to add</sub>
</td>
<td align="center" width="20%">
<h2>4️⃣</h2>
✅<br><strong>Auto-Add</strong><br>
<sub>Approved tests join<br>the suite</sub>
</td>
<td align="center" width="20%">
<h2>5️⃣</h2>
🧠<br><strong>Evolve</strong><br>
<sub>Knowledge grows<br>continuously</sub>
</td>
</tr>
</table>

### 🎯 Real Example of AI Evolution

```
📥 Jira Bug: CNV-75962 "kubevirt-migration-controller OOMKilled at scale"

🤖 AI Analysis:
   ├─ Pattern detected: "OOMKilled" + "migration" + "scale"
   ├─ Component: kubevirt-migration-controller
   └─ Priority: Critical

💡 AI Suggestion:
   "Add new health check: migration_controller_memory"
   - Monitor memory usage of migration controller pods
   - Alert when approaching limits
   - Track during large-scale migrations

✅ Result: New test automatically added to suite!
```

---

## ✨ Features

<table>
<tr>
<td width="33%">

### 🏥 Health Monitoring
- ✅ Node & Operator status
- ✅ Pod health detection
- ✅ KubeVirt/CNV components
- ✅ VM migrations & status
- ✅ Storage health (ODF/CSI)
- ✅ etcd cluster health
- ✅ Certificate expiration

</td>
<td width="33%">

### ⚡ Performance Engineering
- 📊 CPU utilization per node
- 📊 Memory pressure detection
- 📊 I/O bottleneck analysis
- 📊 Network throughput monitoring
- 📊 Resource quota tracking
- 📊 Capacity planning insights
- 📊 Historical trend comparison

</td>
<td width="33%">

### 🧠 AI Capabilities
- 🤖 Self-evolving test suite
- 🤖 Jira bug correlation
- 🤖 Root cause analysis
- 🤖 Pattern recognition
- 🤖 Predictive alerting
- 🤖 Auto-remediation suggestions
- 🤖 Knowledge base learning

</td>
</tr>
</table>

---

## 🏗 Architecture

<table>
<tr>
<td align="center" colspan="4" style="background:#1a237e;color:white;padding:15px;">
<h3>🌐 WEB DASHBOARD (Flask:5000)</h3>
</td>
</tr>
<tr>
<td align="center" width="25%">🏠<br><strong>Dashboard</strong><br><sub>Stats & Status</sub></td>
<td align="center" width="25%">⚙️<br><strong>Configure</strong><br><sub>Build Options</sub></td>
<td align="center" width="25%">📋<br><strong>History</strong><br><sub>Past Builds</sub></td>
<td align="center" width="25%">📄<br><strong>Reports</strong><br><sub>HTML/MD View</sub></td>
</tr>
<tr><td align="center" colspan="4">⬇️</td></tr>
<tr>
<td align="center" colspan="4" style="background:#6a1b9a;color:white;padding:15px;">
<h3>🧠 SELF-EVOLVING AI ENGINE</h3>
<sub>Continuously learns from Jira bugs and adds new tests</sub>
</td>
</tr>
<tr>
<td align="center">🎫<br><strong>Jira Learning</strong><br><sub>Bug patterns</sub></td>
<td align="center">📧<br><strong>Email Learning</strong><br><sub>Team knowledge</sub></td>
<td align="center">🌐<br><strong>Web Learning</strong><br><sub>Docs & forums</sub></td>
<td align="center">🧠<br><strong>Knowledge Base</strong><br><sub>Growing database</sub></td>
</tr>
<tr><td align="center" colspan="4">⬇️</td></tr>
<tr>
<td align="center" colspan="4" style="background:#2e7d32;color:white;padding:15px;">
<h3>⚡ PERFORMANCE ENGINEERING ENGINE</h3>
</td>
</tr>
<tr>
<td align="center">📊<br><strong>Resource Profiler</strong><br><sub>CPU/Memory/IO</sub></td>
<td align="center">🔥<br><strong>Bottleneck Detector</strong><br><sub>Hotspot analysis</sub></td>
<td align="center">📈<br><strong>Trend Analyzer</strong><br><sub>Historical data</sub></td>
<td align="center">⚠️<br><strong>Alert Engine</strong><br><sub>Threshold monitoring</sub></td>
</tr>
<tr><td align="center" colspan="4">⬇️</td></tr>
<tr>
<td align="center" colspan="4" style="background:#e65100;color:white;padding:10px;">
<strong>🔌 INTEGRATIONS</strong>
</td>
</tr>
<tr>
<td align="center">🎫<br><strong>Jira MCP</strong><br><sub>Bug learning</sub></td>
<td align="center">📧<br><strong>Gmail MCP</strong><br><sub>Email learning</sub></td>
<td align="center">🌐<br><strong>Web Search</strong><br><sub>Docs & forums</sub></td>
<td align="center">🤖<br><strong>AI/LLM</strong><br><sub>Deep analysis</sub></td>
</tr>
<tr><td align="center" colspan="4">⬇️</td></tr>
<tr>
<td align="center" colspan="4" style="background:#455a64;color:white;padding:10px;">
<strong>🔐 SSH LAYER (Paramiko)</strong><br>
<sub>Single persistent connection • Auto KUBECONFIG injection</sub>
</td>
</tr>
<tr><td align="center" colspan="4">⬇️</td></tr>
<tr>
<td align="center" colspan="4" style="background:#c62828;color:white;padding:15px;">
<h3>☸️ OPENSHIFT CLUSTER</h3>
</td>
</tr>
<tr>
<td align="center">🖥️<br><strong>Nodes</strong></td>
<td align="center">📦<br><strong>Pods</strong></td>
<td align="center">⚙️<br><strong>Operators</strong></td>
<td align="center">💻<br><strong>VMs</strong></td>
</tr>
<tr>
<td align="center">💾<br><strong>Storage</strong></td>
<td align="center">🗄️<br><strong>etcd</strong></td>
<td align="center">🌐<br><strong>Network</strong></td>
<td align="center">🔒<br><strong>Certs</strong></td>
</tr>
</table>

---

## 📊 Performance Engineering Details

<table>
<tr>
<td width="50%">

### 🔥 What We Monitor

| Metric | Threshold | Action |
|:-------|:----------|:-------|
| **CPU Usage** | >85% | ⚠️ Alert + Analysis |
| **Memory Pressure** | >80% | ⚠️ Alert + OOM Risk |
| **Disk I/O** | Latency >100ms | ⚠️ Storage bottleneck |
| **Network** | Packet loss >1% | ⚠️ Network issues |
| **etcd Latency** | >100ms | 🔴 Critical alert |
| **Pod Density** | >50/node | ⚠️ Capacity warning |

</td>
<td width="50%">

### 📈 Performance Insights

**AI-Powered Analysis:**
- 🎯 Identifies resource hogs
- 🎯 Predicts capacity issues
- 🎯 Recommends optimizations
- 🎯 Tracks degradation trends

**Actionable Reports:**
- 📊 "Node X is 92% CPU - consider spreading VMs"
- 📊 "Migration controller needs more memory"
- 📊 "etcd on slow disk - SSD recommended"

</td>
</tr>
</table>

---

## 🧠 Self-Evolving AI Details

### How It Works

<table>
<tr>
<td align="center" style="background:#2e7d32;color:white;padding:15px;">

**🎫 Learn from Bugs**

Scans Jira for CNV/OCP/ODF:
- Analyzes bug summaries
- Extracts error patterns
- Maps to components
- Tracks resolutions

Automatic test suggestions from bugs.

</td>
<td align="center" style="background:#1565c0;color:white;padding:15px;">

**📧 Learn from Email**

Searches team communications:
- Alert notifications
- Incident discussions
- Troubleshooting threads
- Solution sharing

Captures tribal knowledge automatically.

</td>
<td align="center" style="background:#7b1fa2;color:white;padding:15px;">

**🌐 Learn from Web**

Searches external sources:
- Red Hat documentation
- Knowledge base articles
- Community forums
- Release notes

Stays current with latest fixes.

</td>
</tr>
</table>

### 📈 Evolution Statistics

| Source | What It Learns |
|:-------|:---------------|
| 🎫 **Jira** | CNV, OCPBUGS, ODF bug reports |
| 📧 **Email** | Team alerts, incident threads |
| 🌐 **Web** | Docs, forums, knowledge bases |

| Metric | Value |
|:-------|:------|
| 🧠 Knowledge base entries | 50+ known issues |
| 💡 Auto-suggested checks | 10+ per scan |
| ✅ Current health checks | 17 categories |
| 🔄 Learning frequency | Every build |

---

## 📦 Components

### 1️⃣ Web Dashboard

**`app/`** - Flask-based Jenkins-like UI (formerly `web_dashboard.py`, now modular)

| Page | Description |
|:-----|:------------|
| 🏠 Dashboard | Stats, recent builds, live status |
| ⚙️ Configure | Select checks, set options |
| 📋 History | Past builds with filtering |
| 📝 Console | Real-time output streaming |
| 📄 Reports | View generated HTML reports |

### 2️⃣ Health Check Engine

**`healthchecks/hybrid_health_check.py`** - Core diagnostic system

| Category | Checks | Status Indicators |
|:---------|:-------|:------------------|
| 🏗️ **Infrastructure** | Nodes, Cluster Operators, etcd, MachineConfigPools | Ready/NotReady |
| 📦 **Workloads** | Pods (CrashLoop, Pending, OOM, Unknown) | Running/Failed |
| 💻 **Virtualization** | KubeVirt, VMs, VMIs, Migrations, virt-handler | Running/Migrating |
| 💾 **Storage** | PVCs, CSI, DataVolumes, VolumeSnapshots, ODF | Bound/Pending |
| 📊 **Performance** | CPU, Memory, I/O per node | % utilization |
| 🚨 **Monitoring** | Prometheus alerts | Firing/Resolved |

### 3️⃣ AI Agent System

**`healthchecks/crewai_agents.py`** - CrewAI-based intelligent analysis

<table>
<tr>
<td align="center" colspan="3" style="background:#6a1b9a;color:white;padding:10px;">
<strong>🤖 AI CREW - Performance Engineering Team</strong>
</td>
</tr>
<tr>
<td align="center" width="33%">
🏗️<br><strong>Infra SRE</strong><br>
<sub>• Node health<br>• Operators<br>• etcd perf</sub>
</td>
<td align="center" width="33%">
💻<br><strong>Virt Expert</strong><br>
<sub>• KubeVirt<br>• VM perf<br>• Migrations</sub>
</td>
<td align="center" width="33%">
📊<br><strong>Perf Engineer</strong><br>
<sub>• CPU analysis<br>• Memory profiling<br>• Bottlenecks</sub>
</td>
</tr>
<tr>
<td align="center" colspan="3">⬇️<br>🧠 <strong>Local LLM (Ollama llama3.2:3b)</strong></td>
</tr>
</table>

---

## ⚡ Quick Start

```bash
# 1️⃣ Clone & Setup
cd cnv-health-crew
cp .env.example .env

# 2️⃣ Configure credentials
nano .env
# Set: RH_LAB_HOST, RH_LAB_USER, SSH_KEY_PATH

# 3️⃣ Start Dashboard
./scripts/start_dashboard.sh

# 4️⃣ Open Browser → http://localhost:5000

# 5️⃣ Run with AI Evolution enabled
# Select "Full RCA" + "Jira Integration" in the UI
```

---

## ⚙️ Configuration

### Command Line Options

| Flag | Description |
|:-----|:------------|
| `--server <host>` | Override SSH target |
| `--ai` | Enable full AI root cause analysis |
| `--rca-bugs` | Bug matching only (faster) |
| `--rca-jira` | Search Jira for related bugs |
| `--check-jira` | **Enable AI evolution** - scan for new tests |
| `--email` | Send report via email |

---

## 🔄 Build Process

<table>
<tr>
<td align="center" style="background:#1565c0;color:white;padding:10px;">⚡<br><strong>Init</strong><br><sub>5%</sub></td>
<td align="center">➡️</td>
<td align="center" style="background:#1565c0;color:white;padding:10px;">🔌<br><strong>Connect</strong><br><sub>15%</sub></td>
<td align="center">➡️</td>
<td align="center" style="background:#1565c0;color:white;padding:10px;">📡<br><strong>Collect</strong><br><sub>50%</sub></td>
<td align="center">➡️</td>
<td align="center" style="background:#1565c0;color:white;padding:10px;">🔍<br><strong>Analyze</strong><br><sub>75%</sub></td>
<td align="center">➡️</td>
<td align="center" style="background:#2e7d32;color:white;padding:10px;">📝<br><strong>Report</strong><br><sub>100%</sub></td>
</tr>
</table>

**AI Learning Sources:** 🎫 Jira Bugs → 📧 Team Emails → 🌐 Web Docs → 🧠 Knowledge Base → 💡 New Tests

---

## 🔒 Security

| Aspect | Implementation |
|:-------|:---------------|
| 🔑 SSH Keys | Stored locally, never committed |
| 🛡️ Command Validation | Only `oc`/`kubectl` allowed |
| 🔐 KUBECONFIG | Injected per-command, not stored |
| 📦 Process Isolation | Builds in separate process groups |

---

## 🚀 Roadmap

| 📅 Planned | 💡 Ideas |
|:-----------|:---------|
| ⬜ Scheduled evolution scans | ⬜ Slack/Teams alerts |
| ⬜ Performance trend graphs | ⬜ Prometheus metrics export |
| ⬜ Multi-cluster support | ⬜ Auto-remediation actions |
| ⬜ Custom check plugins | ⬜ ML-based anomaly detection |

---

<p align="center">
  <strong>🧠 AI-Powered • ⚡ Performance Focused • 🔄 Self-Evolving</strong>
</p>

<p align="center">
  <strong>Built with ❤️ for Performance Engineers & SRE Teams</strong>
</p>

<p align="center">
  <sub>Document Version 1.1 • February 2026</sub>
</p>
