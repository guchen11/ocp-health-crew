#!/usr/bin/env python3
"""
CNV Health Dashboard
A Jenkins-like frontend for running health checks and viewing reports
"""

import os
import sys
import json
import glob
import subprocess
import threading
import time
import re
import signal
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, send_from_directory, redirect, url_for

app = Flask(__name__)

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
SCRIPT_PATH = os.path.join(BASE_DIR, "healthchecks", "hybrid_health_check.py")
BUILDS_FILE = os.path.join(BASE_DIR, ".builds.json")

# Available health checks that can be toggled
AVAILABLE_CHECKS = {
    "node_health": {
        "name": "Node Health",
        "description": "Check if all nodes are in Ready state",
        "category": "Infrastructure",
        "default": True
    },
    "cluster_operators": {
        "name": "Cluster Operators",
        "description": "Verify all cluster operators are available and not degraded",
        "category": "Infrastructure",
        "default": True
    },
    "pod_health": {
        "name": "Pod Health",
        "description": "Check for crashed, pending, or unhealthy pods",
        "category": "Workloads",
        "default": True
    },
    "etcd_health": {
        "name": "ETCD Health",
        "description": "Check etcd cluster status and leader election",
        "category": "Infrastructure",
        "default": True
    },
    "kubevirt": {
        "name": "KubeVirt/CNV",
        "description": "Check CNV components and virtual machine status",
        "category": "Virtualization",
        "default": True
    },
    "vm_migrations": {
        "name": "VM Migrations",
        "description": "Check for stuck or failed VM migrations",
        "category": "Virtualization",
        "default": True
    },
    "storage_health": {
        "name": "Storage Health",
        "description": "Check PVCs, CSI drivers, and volume snapshots",
        "category": "Storage",
        "default": True
    },
    "network_health": {
        "name": "Network Health",
        "description": "Check network policies and multus configurations",
        "category": "Network",
        "default": True
    },
    "resource_usage": {
        "name": "Resource Usage",
        "description": "Check CPU and memory utilization across nodes",
        "category": "Resources",
        "default": True
    },
    "certificates": {
        "name": "Certificates",
        "description": "Check for expiring or invalid certificates",
        "category": "Security",
        "default": True
    },
    "machine_config": {
        "name": "Machine Config",
        "description": "Check MachineConfigPool status",
        "category": "Infrastructure",
        "default": True
    },
    "cdi_health": {
        "name": "CDI Health",
        "description": "Check Containerized Data Importer status",
        "category": "Virtualization",
        "default": True
    },
    "hco_health": {
        "name": "HCO Health",
        "description": "Check HyperConverged Operator status",
        "category": "Virtualization",
        "default": True
    },
    "odf_health": {
        "name": "ODF Health",
        "description": "Check OpenShift Data Foundation status",
        "category": "Storage",
        "default": True
    },
    "alerts": {
        "name": "Active Alerts",
        "description": "Check for firing Prometheus alerts",
        "category": "Monitoring",
        "default": True
    }
}

# Store for running jobs
running_jobs = {}
builds = []

def load_builds():
    """Load builds from file"""
    global builds
    if os.path.exists(BUILDS_FILE):
        try:
            with open(BUILDS_FILE, 'r') as f:
                builds = json.load(f)
        except:
            builds = []
    return builds

def save_builds():
    """Save builds to file"""
    with open(BUILDS_FILE, 'w') as f:
        json.dump(builds[-100:], f)  # Keep last 100 builds

def get_next_build_number():
    """Get next build number"""
    if not builds:
        return 1
    return max(b.get('number', 0) for b in builds) + 1

# Load builds on startup
load_builds()

# ============================================================================
# HTML TEMPLATES
# ============================================================================

BASE_CSS = '''
:root {
    --bg-primary: #f8f9fa;
    --bg-secondary: #ffffff;
    --bg-tertiary: #f1f3f5;
    --bg-card: #ffffff;
    --bg-hover: #e9ecef;
    --accent: #0066cc;
    --accent-light: #e7f1ff;
    --success: #28a745;
    --success-light: #d4edda;
    --warning: #ffc107;
    --warning-light: #fff3cd;
    --error: #dc3545;
    --error-light: #f8d7da;
    --purple: #6f42c1;
    --text-primary: #212529;
    --text-secondary: #6c757d;
    --text-muted: #adb5bd;
    --border: #dee2e6;
    --border-light: #e9ecef;
    --header-bg: #1a237e;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 14px;
    line-height: 1.5;
}

/* Header */
.header {
    background: linear-gradient(135deg, #1a237e 0%, #283593 50%, #3949ab 100%);
    padding: 0;
    height: 80px;
    display: flex;
    align-items: center;
    box-shadow: 0 4px 20px rgba(26, 35, 126, 0.3);
}
.header-inner {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 0 30px;
}
.logo {
    display: flex;
    align-items: center;
    gap: 16px;
    color: white;
    text-decoration: none;
}
.logo-img {
    width: 50px;
    height: 50px;
    background: rgba(255,255,255,0.2);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    border: 2px solid rgba(255,255,255,0.3);
}
.logo-text {
    font-size: 28px;
    font-weight: 800;
    color: white;
    text-shadow: 0 2px 10px rgba(0,0,0,0.2);
    letter-spacing: -0.5px;
}
.header-nav {
    margin-left: auto;
    display: flex;
    gap: 8px;
}
.header-nav a {
    color: rgba(255,255,255,0.8);
    text-decoration: none;
    padding: 10px 18px;
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s;
}
.header-nav a:hover, .header-nav a.active {
    background: rgba(255,255,255,0.15);
    color: white;
}

/* Breadcrumb */
.breadcrumb {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 12px 30px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.breadcrumb a {
    color: var(--accent);
    text-decoration: none;
    transition: color 0.2s;
}
.breadcrumb a:hover {
    color: #004499;
    text-decoration: underline;
}
.breadcrumb span {
    color: var(--text-muted);
}

/* Layout */
.container {
    display: flex;
    min-height: calc(100vh - 120px);
}

/* Sidebar */
.sidebar {
    width: 260px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border);
    padding: 20px 0;
}
.sidebar-section {
    margin-bottom: 24px;
}
.sidebar-title {
    padding: 8px 24px;
    font-weight: 600;
    color: var(--text-muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.sidebar-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 24px;
    color: var(--text-secondary);
    text-decoration: none;
    border-left: 3px solid transparent;
    transition: all 0.2s;
}
.sidebar-item:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
    border-left-color: var(--accent);
}
.sidebar-item.active {
    background: var(--accent-light);
    color: var(--accent);
    border-left-color: var(--accent);
}
.sidebar-icon {
    width: 22px;
    text-align: center;
    font-size: 16px;
}

/* Main content */
.main {
    flex: 1;
    padding: 24px;
    background: var(--bg-primary);
}

/* Cards */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 20px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.card-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    font-size: 15px;
    background: var(--bg-tertiary);
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    user-select: none;
    transition: background 0.2s;
}
.card-header:hover {
    background: var(--bg-hover);
}
.card-header .collapse-icon {
    margin-left: auto;
    transition: transform 0.3s;
    color: var(--text-muted);
}
.card-header.collapsed .collapse-icon {
    transform: rotate(-90deg);
}
.card-body {
    padding: 20px;
}
.card-body.collapsed {
    display: none;
}

/* Build History Table */
.build-table {
    width: 100%;
    border-collapse: collapse;
}
.build-table th {
    text-align: left;
    padding: 14px 18px;
    background: var(--bg-tertiary);
    border-bottom: 2px solid var(--border);
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.build-table td {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border-light);
    vertical-align: middle;
}
.build-table tr {
    transition: background 0.2s;
}
.build-table tr:hover {
    background: var(--bg-tertiary);
}

/* Status badges */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
}
.status-success {
    background: var(--success-light);
    color: #155724;
}
.status-failed {
    background: var(--error-light);
    color: #721c24;
}
.status-running {
    background: var(--accent-light);
    color: #004085;
}
.status-unstable {
    background: var(--warning-light);
    color: #856404;
}

/* Status icons */
.status-icon {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    display: inline-block;
}
.status-icon.success { background: var(--success); }
.status-icon.failed { background: var(--error); }
.status-icon.running { background: var(--accent); animation: pulse 1.5s infinite; }
.status-icon.unstable { background: var(--warning); }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* Buttons */
.btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-secondary);
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    text-decoration: none;
    color: var(--text-primary);
    transition: all 0.2s;
}
.btn:hover {
    background: var(--bg-tertiary);
    border-color: var(--text-muted);
    text-decoration: none;
}
.btn-primary {
    background: var(--accent);
    color: white;
    border: none;
}
.btn-primary:hover {
    background: #0052a3;
}
.btn-success {
    background: var(--success);
    color: white;
    border: none;
}
.btn-danger {
    background: var(--error);
    color: white;
    border: none;
}

/* Form elements */
.form-group {
    margin-bottom: 20px;
}
.form-label {
    display: block;
    margin-bottom: 8px;
    font-weight: 500;
    color: var(--text-secondary);
}
.form-input {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 14px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    transition: border-color 0.2s;
}
.form-input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-light);
}

/* Checkbox grid */
.checkbox-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
}
.checkbox-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    transition: all 0.2s;
}
.checkbox-item:hover {
    background: var(--bg-tertiary);
    border-color: var(--accent);
}
.checkbox-item input[type="checkbox"] {
    margin-top: 3px;
    width: 18px;
    height: 18px;
    accent-color: var(--accent);
    cursor: pointer;
}
.checkbox-item label {
    cursor: pointer;
    flex: 1;
}
.checkbox-item .check-name {
    font-weight: 600;
    font-size: 15px;
    display: block;
    margin-bottom: 2px;
    color: var(--text-primary);
}
.checkbox-item .check-desc {
    font-size: 14px;
    color: var(--text-primary);
    line-height: 1.5;
    margin-top: 4px;
}
.checkbox-item .check-category {
    font-size: 10px;
    color: var(--accent);
    background: var(--accent-light);
    padding: 3px 8px;
    border-radius: 4px;
    margin-top: 8px;
    display: inline-block;
}

/* Console */
.console {
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 13px;
    padding: 16px;
    border-radius: 6px;
    max-height: 400px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.5;
}
.console .timestamp {
    color: #888;
}
.console .info { color: #6796e6; }
.console .success { color: #4ec9b0; }
.console .error { color: #f14c4c; }
.console .warning { color: #cca700; }

/* Build timeline */
.timeline {
    position: relative;
    padding-left: 30px;
}
.timeline::before {
    content: '';
    position: absolute;
    left: 10px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--border);
}
.timeline-item {
    position: relative;
    padding-bottom: 20px;
}
.timeline-item::before {
    content: '';
    position: absolute;
    left: -24px;
    top: 4px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--bg-secondary);
}
.timeline-item.success::before { background: var(--success); }
.timeline-item.failed::before { background: var(--error); }

/* Progress bar */
.progress-bar {
    height: 20px;
    background: var(--bg-tertiary);
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border);
}
.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent) 0%, #3399ff 100%);
    transition: width 0.3s;
    border-radius: 10px;
}

/* Stats grid */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 20px;
}
.stat-box {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
}
.stat-box::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: var(--accent);
}
.stat-box:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
.stat-value {
    font-size: 36px;
    font-weight: 700;
    margin-bottom: 6px;
    color: var(--text-primary);
}
.stat-label {
    color: var(--text-secondary);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
}
.stat-box.success::before { background: var(--success); }
.stat-box.success .stat-value { color: var(--success); }
.stat-box.warning::before { background: var(--warning); }
.stat-box.warning .stat-value { color: #b8860b; }
.stat-box.danger::before { background: var(--error); }
.stat-box.danger .stat-value { color: var(--error); }
.stat-box.info::before { background: var(--accent); }
.stat-box.info .stat-value { color: var(--accent); }

/* Links */
a {
    color: var(--accent);
    text-decoration: none;
    transition: color 0.2s;
}
a:hover {
    color: #004499;
    text-decoration: underline;
}

/* Build number link */
.build-link {
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--accent);
}

/* Empty state */
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-secondary);
}
.empty-state h3 {
    margin-bottom: 10px;
    color: var(--text-primary);
    font-size: 16px;
}

/* Category headers */
.category-header {
    background: var(--bg-tertiary);
    padding: 10px 16px;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 20px;
    margin-bottom: 12px;
    border-radius: 6px;
    border-left: 4px solid var(--accent);
}

/* Report preview */
.report-preview {
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--bg-tertiary);
}
.report-preview iframe {
    width: 100%;
    height: 600px;
    border: none;
}

/* Collapsible sections */
.collapsible-header {
    cursor: pointer;
    user-select: none;
}
.collapsible-header:hover {
    background: var(--bg-hover);
}
.collapse-icon {
    transition: transform 0.2s;
}
.collapsed .collapse-icon {
    transform: rotate(-90deg);
}
.category-content.collapsed {
    display: none;
}
.category-header:hover {
    background: var(--bg-hover);
}

/* Phases */
.phase-item {
    transition: all 0.3s;
}
.phase-item.done {
    background: var(--success-light) !important;
    border-color: var(--success) !important;
}
.phase-item.running {
    background: var(--accent-light) !important;
    border-color: var(--accent) !important;
    animation: phase-pulse 1.5s infinite;
}
.phase-item.error {
    background: var(--error-light) !important;
    border-color: var(--error) !important;
}
@keyframes phase-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>CNV Health Dashboard</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
            <nav class="header-nav">
                <a href="/">Dashboard</a>
                <a href="/job/configure">New Build</a>
                <a href="/job/history">Build History</a>
                <a href="/help">Help</a>
            </nav>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <span>Overview</span>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Quick Actions</div>
                <a href="/job/configure" class="sidebar-item">
                    <span class="sidebar-icon">▶️</span>
                    Build with Parameters
                </a>
                <a href="/job/quick-run" class="sidebar-item">
                    <span class="sidebar-icon">⚡</span>
                    Quick Build (All Checks)
                </a>
                <a href="/job/history" class="sidebar-item">
                    <span class="sidebar-icon">📋</span>
                    Build History
                </a>
            </div>
            <div class="sidebar-section">
                <div class="sidebar-title">Recent Builds</div>
                {% for build in recent_builds[:5] %}
                <a href="/job/{{ build.number }}" class="sidebar-item">
                    <span class="status-icon {{ build.status }}"></span>
                    #{{ build.number }} - {{ build.timestamp[:16] }}
                </a>
                {% endfor %}
            </div>
        </aside>
        
        <main class="main">
            {% if not running_build %}
            <!-- Stats - Hidden during build -->
            <div class="card">
                <div class="card-header" onclick="toggleCard(this)">
                    📊 Build Statistics
                    <span class="collapse-icon" style="margin-left:auto;">▼</span>
                </div>
                <div class="card-body">
                    <div class="stats-grid">
                        <div class="stat-box info">
                            <div class="stat-value">{{ stats.total }}</div>
                            <div class="stat-label">Total Builds</div>
                        </div>
                        <div class="stat-box success">
                            <div class="stat-value">{{ stats.success }}</div>
                            <div class="stat-label">Successful</div>
                        </div>
                        <div class="stat-box warning">
                            <div class="stat-value">{{ stats.unstable }}</div>
                            <div class="stat-label">Issues Found</div>
                        </div>
                        <div class="stat-box danger">
                            <div class="stat-value">{{ stats.failed }}</div>
                            <div class="stat-label">Failed</div>
                        </div>
                    </div>
                </div>
            </div>
            {% endif %}
            
            <!-- Running Build -->
            {% if running_build %}
            <div class="card">
                <div class="card-header">
                    <span class="status-icon running"></span>
                    Build #{{ running_build.number }} - Running
                    <button onclick="stopBuild()" class="btn btn-danger" style="margin-left:auto;padding:6px 16px;">
                        ⏹️ Stop Build
                    </button>
                    <span class="collapse-icon" style="margin-left:12px;cursor:pointer;" onclick="toggleCard(this.parentElement)">▼</span>
                </div>
                <div class="card-body">
                    <!-- Combined Phases & Progress -->
                    <div id="phases-progress" style="margin-bottom:20px;">
                        <!-- Phase Labels -->
                        <div id="phases" style="display:grid;grid-template-columns:repeat({{ running_build.phases|length }}, 1fr);gap:2px;margin-bottom:8px;">
                            {% for phase in running_build.phases %}
                            <div class="phase-label {{ phase.status }}" style="text-align:center;padding:8px 4px;font-size:12px;font-weight:500;
                                {% if phase.status == 'done' %}color:var(--success);{% elif phase.status == 'running' %}color:var(--accent);{% elif phase.status == 'error' %}color:var(--error);{% else %}color:var(--text-secondary);{% endif %}">
                                <span class="phase-icon" style="display:block;font-size:16px;margin-bottom:4px;">
                                    {% if phase.status == 'done' %}✅
                                    {% elif phase.status == 'running' %}🔄
                                    {% elif phase.status == 'error' %}❌
                                    {% else %}⏳{% endif %}
                                </span>
                                {{ phase.name }}
                            </div>
                            {% endfor %}
                        </div>
                        <!-- Progress Bar aligned with phases -->
                        <div style="display:grid;grid-template-columns:repeat({{ running_build.phases|length }}, 1fr);gap:2px;height:8px;background:var(--bg-tertiary);border-radius:4px;overflow:hidden;">
                            {% for phase in running_build.phases %}
                            <div class="phase-progress" style="height:100%;transition:background 0.3s;
                                {% if phase.status == 'done' %}background:var(--success);
                                {% elif phase.status == 'running' %}background:linear-gradient(90deg, var(--accent) 0%, var(--bg-tertiary) 100%);animation:pulse 1s infinite;
                                {% elif phase.status == 'error' %}background:var(--error);
                                {% else %}background:var(--bg-tertiary);{% endif %}">
                            </div>
                            {% endfor %}
                        </div>
                        <!-- Progress percentage -->
                        <div style="display:flex;justify-content:flex-end;margin-top:6px;">
                            <span id="progress-text" style="font-size:12px;color:var(--text-secondary);">{{ running_build.progress }}%</span>
                        </div>
                    </div>
                    <!-- Current Phase Message -->
                    <div id="current-phase" style="padding:12px 16px;background:var(--accent-light);border-radius:8px;margin-bottom:15px;border-left:4px solid var(--accent);">
                        <span style="font-weight:600;">{{ running_build.current_phase or 'Initializing...' }}</span>
                    </div>
                    <!-- Console -->
                    <div class="card" style="margin:0;">
                        <div class="card-header" onclick="toggleCard(this)" style="padding:10px 16px;">
                            📝 Console Output
                            <span class="collapse-icon" style="margin-left:auto;">▼</span>
                        </div>
                        <div class="card-body" style="padding:0;">
                            <div class="console" id="console" style="border-radius:0;">{{ running_build.output }}</div>
                        </div>
                    </div>
                </div>
            </div>
            {% endif %}
            
            {% if not running_build %}
            <!-- Build History - Hidden during build -->
            <div class="card">
                <div class="card-header" onclick="toggleCard(this)">
                    📋 Recent Build History
                    <span class="collapse-icon" style="margin-left:auto;">▼</span>
                    <button id="deleteSelectedBtn" onclick="event.stopPropagation(); deleteSelected()" class="btn btn-danger" style="margin-left:16px;display:none;">
                        🗑️ Delete Selected (<span id="selectedCount">0</span>)
                    </button>
                </div>
                <div class="card-body" style="padding:0;">
                    {% if builds %}
                    <table class="build-table">
                        <thead>
                            <tr>
                                <th style="width:40px;"><input type="checkbox" id="selectAll" onchange="toggleSelectAll()"></th>
                                <th style="width:60px;">Build</th>
                                <th>Status</th>
                                <th>Checks Run</th>
                                <th>Started</th>
                                <th>Duration</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for build in builds %}
                            <tr>
                                <td><input type="checkbox" class="build-checkbox" value="{{ build.number }}" onchange="updateSelectedCount()"></td>
                                <td>
                                    <a href="/job/{{ build.number }}" class="build-link">
                                        <span class="status-icon {{ build.status }}"></span>
                                        #{{ build.number }}
                                    </a>
                                </td>
                                <td>
                                    <span class="status-badge status-{{ build.status }}">
                                        {{ build.status_text }}
                                    </span>
                                </td>
                                <td>{{ build.checks_count }} checks</td>
                                <td>{{ build.timestamp }}</td>
                                <td>{{ build.duration }}</td>
                                <td>
                                    {% if build.report_file %}
                                    <a href="/report/{{ build.report_file }}" class="btn" target="_blank">📄 Report</a>
                                    {% endif %}
                                    <a href="/job/{{ build.number }}/console" class="btn">📝 Console</a>
                                    <button onclick="deleteBuild({{ build.number }})" class="btn" style="color:var(--error);" title="Delete">🗑️</button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% else %}
                    <div class="empty-state">
                        <h3>No builds yet</h3>
                        <p>Click "Build with Parameters" to run your first health check</p>
                    </div>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </main>
    </div>
    
    <script>
        function toggleCard(header) {
            header.classList.toggle('collapsed');
            var body = header.nextElementSibling;
            if (body && body.classList.contains('card-body')) {
                body.classList.toggle('collapsed');
            }
        }
        
        function toggleSelectAll() {
            var selectAll = document.getElementById('selectAll').checked;
            document.querySelectorAll('.build-checkbox').forEach(function(cb) {
                cb.checked = selectAll;
            });
            updateSelectedCount();
        }
        
        function updateSelectedCount() {
            var count = document.querySelectorAll('.build-checkbox:checked').length;
            document.getElementById('selectedCount').textContent = count;
            document.getElementById('deleteSelectedBtn').style.display = count > 0 ? 'inline-flex' : 'none';
        }
        
        function deleteSelected() {
            var selected = [];
            document.querySelectorAll('.build-checkbox:checked').forEach(function(cb) {
                selected.push(cb.value);
            });
            
            if (selected.length === 0) return;
            
            if (confirm('Are you sure you want to delete ' + selected.length + ' build(s) and their reports?')) {
                Promise.all(selected.map(function(buildNum) {
                    return fetch('/api/delete/' + buildNum, { method: 'POST' });
                })).then(function() {
                    location.reload();
                });
            }
        }
        
        function deleteBuild(buildNum) {
            if (confirm('Are you sure you want to delete Build #' + buildNum + ' and its report?')) {
                fetch('/api/delete/' + buildNum, { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            location.reload();
                        } else {
                            alert('Failed to delete: ' + data.error);
                        }
                    });
            }
        }
    </script>
    {% if running_build %}
    <script>
        function updatePhases(phases) {
            var container = document.getElementById('phases-progress');
            if (!container || !phases) return;
            
            // Build phase labels
            var labelsHtml = '<div id="phases" style="display:grid;grid-template-columns:repeat(' + phases.length + ', 1fr);gap:2px;margin-bottom:8px;">';
            phases.forEach(function(phase) {
                var icon = phase.status === 'done' ? '✅' : 
                           phase.status === 'running' ? '🔄' : 
                           phase.status === 'error' ? '❌' : '⏳';
                var color = phase.status === 'done' ? 'var(--success)' : 
                            phase.status === 'running' ? 'var(--accent)' : 
                            phase.status === 'error' ? 'var(--error)' : 'var(--text-secondary)';
                labelsHtml += '<div class="phase-label ' + phase.status + '" style="text-align:center;padding:8px 4px;font-size:12px;font-weight:500;color:' + color + ';">';
                labelsHtml += '<span class="phase-icon" style="display:block;font-size:16px;margin-bottom:4px;">' + icon + '</span>';
                labelsHtml += phase.name;
                labelsHtml += '</div>';
            });
            labelsHtml += '</div>';
            
            // Build progress bar segments
            var progressHtml = '<div style="display:grid;grid-template-columns:repeat(' + phases.length + ', 1fr);gap:2px;height:8px;background:var(--bg-tertiary);border-radius:4px;overflow:hidden;">';
            phases.forEach(function(phase) {
                var bg = phase.status === 'done' ? 'var(--success)' : 
                         phase.status === 'running' ? 'linear-gradient(90deg, var(--accent) 0%, var(--bg-tertiary) 100%)' : 
                         phase.status === 'error' ? 'var(--error)' : 'var(--bg-tertiary)';
                var anim = phase.status === 'running' ? 'animation:pulse 1s infinite;' : '';
                progressHtml += '<div class="phase-progress" style="height:100%;transition:background 0.3s;background:' + bg + ';' + anim + '"></div>';
            });
            progressHtml += '</div>';
            
            // Progress percentage (will be updated separately)
            var percentHtml = '<div style="display:flex;justify-content:flex-end;margin-top:6px;"><span id="progress-text" style="font-size:12px;color:var(--text-secondary);">0%</span></div>';
            
            container.innerHTML = labelsHtml + progressHtml + percentHtml;
        }
        
        function stopBuild() {
            if (confirm('Are you sure you want to stop the running build?')) {
                fetch('/api/stop', { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            location.reload();
                        } else {
                            alert('Failed to stop build: ' + data.error);
                        }
                    });
            }
        }
        
        setInterval(function() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        document.getElementById('console').innerHTML = data.output;
                        document.getElementById('console').scrollTop = document.getElementById('console').scrollHeight;
                        var progressText = document.getElementById('progress-text');
                        if (progressText) progressText.textContent = data.progress + '%';
                        if (data.current_phase) {
                            document.getElementById('current-phase').innerHTML = '<span style="font-weight:600;">' + data.current_phase + '</span>';
                        }
                        updatePhases(data.phases);
                    } else {
                        location.reload();
                    }
                });
        }, 1000);
    </script>
    {% endif %}
</body>
</html>
'''

CONFIGURE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>{% if preset == 'all' %}Quick Build{% else %}Build with Parameters{% endif %} - CNV Health</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
            <nav class="header-nav">
                <a href="/">Dashboard</a>
                <a href="/job/configure" class="active">New Build</a>
                <a href="/job/history">Build History</a>
                <a href="/help">Help</a>
            </nav>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <a href="/job/configure">Build with Parameters</a>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Build Options</div>
                <a href="/job/configure" class="sidebar-item active">
                    <span class="sidebar-icon">⚙️</span>
                    Configure Build
                </a>
                <a href="/job/quick-run" class="sidebar-item">
                    <span class="sidebar-icon">⚡</span>
                    Quick Build
                </a>
            </div>
            <div class="sidebar-section">
                <div class="sidebar-title">Presets</div>
                <a href="#" onclick="selectAll()" class="sidebar-item">
                    <span class="sidebar-icon">✅</span>
                    Select All Checks
                </a>
                <a href="#" onclick="selectNone()" class="sidebar-item">
                    <span class="sidebar-icon">⬜</span>
                    Deselect All
                </a>
                <a href="#" onclick="selectInfra()" class="sidebar-item">
                    <span class="sidebar-icon">🏗️</span>
                    Infrastructure Only
                </a>
                <a href="#" onclick="selectVirt()" class="sidebar-item">
                    <span class="sidebar-icon">💻</span>
                    Virtualization Only
                </a>
            </div>
        </aside>
        
        <main class="main">
            {% if preset == 'all' %}
            <div style="background:var(--success-light);border:1px solid var(--success);border-radius:8px;padding:16px 20px;margin-bottom:20px;display:flex;align-items:center;gap:12px;">
                <span style="font-size:24px;">⚡</span>
                <div>
                    <div style="font-weight:600;color:var(--success);font-size:16px;">Quick Build Mode</div>
                    <div style="color:var(--text-secondary);font-size:13px;">All checks are pre-selected. Review and click "Run Now" to start.</div>
                </div>
            </div>
            {% endif %}
            <form action="/job/run" method="POST">
                <!-- Target Server -->
                <div class="card">
                    <div class="card-header" onclick="toggleCard(this)">
                        🖥️ Target Server
                        <span class="collapse-icon" style="margin-left:auto;">▼</span>
                    </div>
                    <div class="card-body">
                        <div style="margin-bottom:12px;">
                            <label for="server_host" style="display:block;font-weight:600;margin-bottom:8px;color:var(--text);">Server Hostname / IP</label>
                            <input type="text" id="server_host" name="server_host" 
                                placeholder="e.g. f04-h10-000-r640.rdu2.scalelab.redhat.com" 
                                style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;font-size:14px;background:var(--bg-secondary);"
                                value="{{ server_host or '' }}">
                            <span style="font-size:12px;color:var(--text-secondary);margin-top:6px;display:block;">
                                💡 Leave empty to use default kubeconfig, or enter the target server hostname to connect via SSH
                            </span>
                        </div>
                    </div>
                </div>
                
                <!-- General Options -->
                <div class="card">
                    <div class="card-header" onclick="toggleCard(this)">
                        ⚙️ Build Options
                        <span class="collapse-icon" style="margin-left:auto;">▼</span>
                    </div>
                    <div class="card-body">
                        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:20px;">
                            <div class="checkbox-item">
                                <input type="checkbox" id="opt_jira" name="check_jira" {{ 'checked' if preset == 'all' else '' }}>
                                <label for="opt_jira">
                                    <span class="check-name">🔍 Jira Integration</span>
                                    <span class="check-desc">Check Jira for recent bugs & suggest adding new tests</span>
                                </label>
                            </div>
                            <div class="checkbox-item" style="flex-direction:column;align-items:stretch;">
                                <div style="display:flex;align-items:flex-start;gap:12px;">
                                    <input type="checkbox" id="opt_email" name="send_email" style="margin-top:3px;" {{ 'checked' if preset == 'all' else '' }}>
                                    <label for="opt_email">
                                        <span class="check-name">📤 Email Report</span>
                                        <span class="check-desc">Send report via email</span>
                                    </label>
                                </div>
                                <input type="email" name="email_to" id="email_to" placeholder="Enter email address (e.g. user@redhat.com)" 
                                    style="margin-top:10px;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;width:100%;"
                                    value="guchen@redhat.com">
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Root Cause Analysis -->
                <div class="card">
                    <div class="card-header" onclick="toggleCard(this)">
                        🔬 Root Cause Analysis
                        <span class="collapse-icon" style="margin-left:auto;">▼</span>
                    </div>
                    <div class="card-body">
                        <!-- RCA Level Selection -->
                        <div style="margin-bottom:20px;">
                            <div style="font-weight:600;color:var(--text);margin-bottom:12px;font-size:14px;">Analysis Level</div>
                            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
                                <label class="rca-option" style="display:flex;flex-direction:column;padding:16px;border:2px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.2s;">
                                    <input type="radio" name="rca_level" value="none" style="margin-bottom:8px;" onchange="toggleRcaSources()" {{ '' if preset == 'all' else 'checked' }}>
                                    <span style="font-weight:600;color:var(--text);font-size:14px;">📋 Checks Only</span>
                                    <span style="color:var(--text-secondary);font-size:12px;margin-top:4px;">Run health checks without analysis</span>
                                </label>
                                <label class="rca-option" style="display:flex;flex-direction:column;padding:16px;border:2px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.2s;">
                                    <input type="radio" name="rca_level" value="bugs" style="margin-bottom:8px;" onchange="toggleRcaSources()">
                                    <span style="font-weight:600;color:var(--text);font-size:14px;">🐛 Bug Digging</span>
                                    <span style="color:var(--text-secondary);font-size:12px;margin-top:4px;">Match failures to known bugs</span>
                                </label>
                                <label class="rca-option" style="display:flex;flex-direction:column;padding:16px;border:2px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.2s;">
                                    <input type="radio" name="rca_level" value="full" style="margin-bottom:8px;" onchange="toggleRcaSources()" {{ 'checked' if preset == 'all' else '' }}>
                                    <span style="font-weight:600;color:var(--text);font-size:14px;">🔍 Full RCA</span>
                                    <span style="color:var(--text-secondary);font-size:12px;margin-top:4px;">Deep investigation & root cause</span>
                                </label>
                            </div>
                        </div>
                        <!-- RCA Data Sources (shown when bugs or full is selected) -->
                        <div id="rca-sources" style="display:none;">
                            <hr style="border:none;border-top:1px solid var(--border);margin:20px 0;">
                            <div style="font-weight:600;color:var(--text);margin-bottom:12px;font-size:14px;">📚 Data Sources for Bug Digging</div>
                            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
                                <div class="checkbox-item" style="padding:12px;border:1px solid var(--border);border-radius:8px;">
                                    <input type="checkbox" id="opt_jira_rca" name="rca_jira" {{ 'checked' if preset == 'all' else 'checked' }}>
                                    <label for="opt_jira_rca">
                                        <span class="check-name">🎫 Jira Bugs</span>
                                        <span class="check-desc">Search Jira for matching bugs & known issues</span>
                                    </label>
                                </div>
                                <div class="checkbox-item" style="padding:12px;border:1px solid var(--border);border-radius:8px;">
                                    <input type="checkbox" id="opt_email_rca" name="rca_email" {{ 'checked' if preset == 'all' else '' }}>
                                    <label for="opt_email_rca">
                                        <span class="check-name">📧 Email Search</span>
                                        <span class="check-desc">Search Gmail for related discussions & alerts</span>
                                    </label>
                                </div>
                                <div class="checkbox-item" style="padding:12px;border:1px solid var(--border);border-radius:8px;">
                                    <input type="checkbox" id="opt_web_rca" name="rca_web" {{ 'checked' if preset == 'all' else '' }}>
                                    <label for="opt_web_rca">
                                        <span class="check-name">🌐 Web Search</span>
                                        <span class="check-desc">Search docs, forums & knowledge bases</span>
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Health Checks Selection -->
                <div class="card">
                    <div class="card-header" onclick="toggleCard(this)">
                        🔍 Select Health Checks to Run
                        <span class="collapse-icon" style="margin-left:auto;">▼</span>
                    </div>
                    <div class="card-body">
                        {% for category in categories %}
                        <div class="category-header" onclick="toggleCategory(this)" style="cursor:pointer;display:flex;align-items:center;">
                            {{ category }}
                            <span class="collapse-icon" style="margin-left:auto;font-size:12px;">▼</span>
                        </div>
                        <div class="checkbox-grid category-content">
                            {% for check_id, check in checks.items() %}
                            {% if check.category == category %}
                            <div class="checkbox-item">
                                <input type="checkbox" id="check_{{ check_id }}" name="checks" value="{{ check_id }}" 
                                    {{ 'checked' if (preset == 'all' or check.default) else '' }} class="check-input" data-category="{{ check.category }}">
                                <label for="check_{{ check_id }}">
                                    <span class="check-name">{{ check.name }}</span>
                                    <span class="check-desc">{{ check.description }}</span>
                                </label>
                            </div>
                            {% endif %}
                            {% endfor %}
                        </div>
                        {% endfor %}
                    </div>
                </div>
                
                <!-- Submit -->
                <div style="display:flex;gap:12px;margin-top:20px;">
                    <button type="submit" class="btn btn-primary" style="padding:12px 30px;font-size:14px;">
                        ▶️ Run Now
                    </button>
                    <a href="/" class="btn">Cancel</a>
                </div>
            </form>
        </main>
    </div>
    
    <script>
        function toggleCard(header) {
            header.classList.toggle('collapsed');
            var body = header.nextElementSibling;
            if (body && body.classList.contains('card-body')) {
                body.classList.toggle('collapsed');
            }
        }
        function toggleCategory(header) {
            header.classList.toggle('collapsed');
            var content = header.nextElementSibling;
            if (content && content.classList.contains('category-content')) {
                content.classList.toggle('collapsed');
            }
        }
        function selectAll() {
            document.querySelectorAll('.check-input').forEach(cb => cb.checked = true);
            // Set RCA to full and check other options
            document.querySelector('input[name="rca_level"][value="full"]').checked = true;
            document.getElementById('opt_jira_rca').checked = true;
            document.getElementById('opt_email_rca').checked = true;
            document.getElementById('opt_jira').checked = true;
            document.getElementById('opt_email').checked = true;
            toggleRcaSources();
            return false;
        }
        function selectNone() {
            document.querySelectorAll('.check-input').forEach(cb => cb.checked = false);
            // Set RCA to none and uncheck other options
            document.querySelector('input[name="rca_level"][value="none"]').checked = true;
            document.getElementById('opt_jira_rca').checked = false;
            document.getElementById('opt_email_rca').checked = false;
            document.getElementById('opt_jira').checked = false;
            document.getElementById('opt_email').checked = false;
            toggleRcaSources();
            return false;
        }
        function updateRcaStyles() {
            document.querySelectorAll('.rca-option').forEach(opt => {
                var radio = opt.querySelector('input[type="radio"]');
                if (radio.checked) {
                    opt.style.borderColor = 'var(--primary)';
                    opt.style.background = 'var(--primary-light)';
                } else {
                    opt.style.borderColor = 'var(--border)';
                    opt.style.background = 'transparent';
                }
            });
        }
        function toggleRcaSources() {
            var rcaLevel = document.querySelector('input[name="rca_level"]:checked').value;
            var sourcesDiv = document.getElementById('rca-sources');
            if (rcaLevel === 'bugs' || rcaLevel === 'full') {
                sourcesDiv.style.display = 'block';
            } else {
                sourcesDiv.style.display = 'none';
            }
            updateRcaStyles();
        }
        document.querySelectorAll('input[name="rca_level"]').forEach(r => r.addEventListener('change', toggleRcaSources));
        toggleRcaSources();
        function selectInfra() {
            document.querySelectorAll('.check-input').forEach(cb => {
                cb.checked = cb.dataset.category === 'Infrastructure';
            });
            return false;
        }
        function selectVirt() {
            document.querySelectorAll('.check-input').forEach(cb => {
                cb.checked = cb.dataset.category === 'Virtualization';
            });
            return false;
        }
    </script>
</body>
</html>
'''

BUILD_DETAIL_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Build #{{ build.number }} - CNV Health</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
            <nav class="header-nav">
                <a href="/">Dashboard</a>
                <a href="/job/configure">New Build</a>
                <a href="/job/history">Build History</a>
                <a href="/help">Help</a>
            </nav>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <a href="/job/history">Builds</a>
        <span>›</span>
        <span>#{{ build.number }}</span>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Build #{{ build.number }}</div>
                <a href="/job/{{ build.number }}" class="sidebar-item active">
                    <span class="sidebar-icon">📊</span>
                    Build Summary
                </a>
                <a href="/job/{{ build.number }}/console" class="sidebar-item">
                    <span class="sidebar-icon">📝</span>
                    Console Output
                </a>
                {% if build.report_file %}
                <a href="/report/{{ build.report_file }}" class="sidebar-item" target="_blank">
                    <span class="sidebar-icon">📄</span>
                    View Report
                </a>
                {% endif %}
            </div>
            <div class="sidebar-section">
                <div class="sidebar-title">Actions</div>
                <a href="/job/rebuild/{{ build.number }}" class="sidebar-item">
                    <span class="sidebar-icon">🔄</span>
                    Rebuild
                </a>
                <a href="/job/configure" class="sidebar-item">
                    <span class="sidebar-icon">▶️</span>
                    New Build
                </a>
            </div>
        </aside>
        
        <main class="main">
            <div class="card">
                <div class="card-header">
                    <span class="status-icon {{ build.status }}"></span>
                    Build #{{ build.number }} - {{ build.status_text }}
                </div>
                <div class="card-body">
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:20px;">
                        <div>
                            <strong style="color:var(--text-light);font-size:11px;text-transform:uppercase;">Started</strong>
                            <div>{{ build.timestamp }}</div>
                        </div>
                        <div>
                            <strong style="color:var(--text-light);font-size:11px;text-transform:uppercase;">Duration</strong>
                            <div>{{ build.duration }}</div>
                        </div>
                        <div>
                            <strong style="color:var(--text-light);font-size:11px;text-transform:uppercase;">Checks Run</strong>
                            <div>{{ build.checks_count }} checks</div>
                        </div>
                        <div>
                            <strong style="color:var(--text-light);font-size:11px;text-transform:uppercase;">Server</strong>
                            <div style="font-family:monospace;font-size:12px;">{{ build.options.server_host or 'Default (env)' }}</div>
                        </div>
                        <div>
                            <strong style="color:var(--text-light);font-size:11px;text-transform:uppercase;">Options</strong>
                            <div>
                                {% if build.options.rca_level == 'full' %}🔍 Full RCA {% elif build.options.rca_level == 'bugs' %}🐛 Bug Match {% else %}📋 Checks {% endif %}
                                {% if build.options.rca_jira %}🎫 Jira {% endif %}
                                {% if build.options.rca_email %}📧 Email {% endif %}
                                {% if build.options.rca_web %}🌐 Web {% endif %}
                                {% if build.options.jira %}🔎 Suggest {% endif %}
                                {% if build.options.email %}📤 {{ build.options.email_to or 'Send' }} {% endif %}
                            </div>
                        </div>
                    </div>
                    
                    {% if build.checks %}
                    <h4 style="margin-bottom:15px;">Checks Executed:</h4>
                    <div class="checkbox-grid">
                        {% for check in build.checks %}
                        <div class="checkbox-item" style="background:{% if check in checks %}#e8f5e9{% else %}#f5f5f5{% endif %};">
                            <span>{% if check in checks %}✅{% else %}⬜{% endif %}</span>
                            <span>{{ checks.get(check, {}).get('name', check) }}</span>
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
            </div>
            
            {% if build.report_file %}
            <div class="card">
                <div class="card-header">📄 Report Preview</div>
                <div class="card-body" style="padding:0;">
                    <div class="report-preview">
                        <iframe src="/report/{{ build.report_file }}"></iframe>
                    </div>
                </div>
            </div>
            {% endif %}
        </main>
    </div>
</body>
</html>
'''

CONSOLE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Console Output - Build #{{ build.number }}</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''
    .console-full {
        background: #1e1e1e;
        color: #d4d4d4;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 13px;
        padding: 20px;
        min-height: 500px;
        white-space: pre-wrap;
        word-break: break-word;
    }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <a href="/job/{{ build.number }}">Build #{{ build.number }}</a>
        <span>›</span>
        <span>Console Output</span>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Build #{{ build.number }}</div>
                <a href="/job/{{ build.number }}" class="sidebar-item">
                    <span class="sidebar-icon">📊</span>
                    Build Summary
                </a>
                <a href="/job/{{ build.number }}/console" class="sidebar-item active">
                    <span class="sidebar-icon">📝</span>
                    Console Output
                </a>
            </div>
        </aside>
        
        <main class="main">
            <div class="card">
                <div class="card-header">📝 Console Output</div>
                <div class="card-body" style="padding:0;">
                    <div class="console-full" id="console">{{ build.output }}</div>
                </div>
            </div>
        </main>
    </div>
    
    {% if build.status == 'running' %}
    <script>
        setInterval(function() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('console').innerHTML = data.output;
                    document.getElementById('console').scrollTop = document.getElementById('console').scrollHeight;
                    if (!data.running) location.reload();
                });
        }, 2000);
    </script>
    {% endif %}
</body>
</html>
'''

HISTORY_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Build History - CNV Health</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
            <nav class="header-nav">
                <a href="/">Dashboard</a>
                <a href="/job/configure">New Build</a>
                <a href="/job/history" class="active">Build History</a>
                <a href="/help">Help</a>
            </nav>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <span>Build History</span>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Filter</div>
                <a href="/job/history" class="sidebar-item active">
                    <span class="sidebar-icon">📋</span>
                    All Builds
                </a>
                <a href="/job/history?status=success" class="sidebar-item">
                    <span class="sidebar-icon">✅</span>
                    Successful
                </a>
                <a href="/job/history?status=unstable" class="sidebar-item">
                    <span class="sidebar-icon">⚠️</span>
                    With Issues
                </a>
                <a href="/job/history?status=failed" class="sidebar-item">
                    <span class="sidebar-icon">❌</span>
                    Failed
                </a>
            </div>
        </aside>
        
        <main class="main">
            <div class="card">
                <div class="card-header">
                    📋 Build History
                    <span style="margin-left:auto;font-weight:normal;color:var(--text-light);">{{ builds|length }} builds</span>
                    <button id="deleteSelectedBtn" onclick="deleteSelected()" class="btn btn-danger" style="margin-left:16px;display:none;">
                        🗑️ Delete Selected (<span id="selectedCount">0</span>)
                    </button>
                </div>
                <div class="card-body" style="padding:0;">
                    {% if builds %}
                    <table class="build-table">
                        <thead>
                            <tr>
                                <th style="width:40px;"><input type="checkbox" id="selectAll" onchange="toggleSelectAll()"></th>
                                <th>Build</th>
                                <th>Status</th>
                                <th>Checks</th>
                                <th>Options</th>
                                <th>Started</th>
                                <th>Duration</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for build in builds %}
                            <tr>
                                <td><input type="checkbox" class="build-checkbox" value="{{ build.number }}" onchange="updateSelectedCount()"></td>
                                <td>
                                    <a href="/job/{{ build.number }}" class="build-link">
                                        <span class="status-icon {{ build.status }}"></span>
                                        #{{ build.number }}
                                    </a>
                                </td>
                                <td>
                                    <span class="status-badge status-{{ build.status }}">
                                        {{ build.status_text }}
                                    </span>
                                </td>
                                <td>{{ build.checks_count }}</td>
                                <td>
                                    {% if build.options.rca_level == 'full' %}🔍{% elif build.options.rca_level == 'bugs' %}🐛{% else %}📋{% endif %}
                                    {% if build.options.rca_jira %}🎫{% endif %}
                                    {% if build.options.rca_email %}📧{% endif %}
                                    {% if build.options.rca_web %}🌐{% endif %}
                                    {% if build.options.email %}📤{% endif %}
                                </td>
                                <td>{{ build.timestamp }}</td>
                                <td>{{ build.duration }}</td>
                                <td>
                                    {% if build.report_file %}
                                    <a href="/report/{{ build.report_file }}" class="btn" target="_blank">📄</a>
                                    {% endif %}
                                    <a href="/job/{{ build.number }}/console" class="btn">📝</a>
                                    <a href="/job/rebuild/{{ build.number }}" class="btn">🔄</a>
                                    <button onclick="deleteBuild({{ build.number }})" class="btn" style="color:var(--error);" title="Delete">🗑️</button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% else %}
                    <div class="empty-state">
                        <h3>No builds found</h3>
                    </div>
                    {% endif %}
                </div>
            </div>
        </main>
    </div>
    <script>
        function toggleSelectAll() {
            var selectAll = document.getElementById('selectAll').checked;
            document.querySelectorAll('.build-checkbox').forEach(function(cb) {
                cb.checked = selectAll;
            });
            updateSelectedCount();
        }
        
        function updateSelectedCount() {
            var count = document.querySelectorAll('.build-checkbox:checked').length;
            document.getElementById('selectedCount').textContent = count;
            document.getElementById('deleteSelectedBtn').style.display = count > 0 ? 'inline-flex' : 'none';
        }
        
        function deleteSelected() {
            var selected = [];
            document.querySelectorAll('.build-checkbox:checked').forEach(function(cb) {
                selected.push(cb.value);
            });
            
            if (selected.length === 0) return;
            
            if (confirm('Are you sure you want to delete ' + selected.length + ' build(s) and their reports?')) {
                Promise.all(selected.map(function(buildNum) {
                    return fetch('/api/delete/' + buildNum, { method: 'POST' });
                })).then(function() {
                    location.reload();
                });
            }
        }
        
        function deleteBuild(buildNum) {
            if (confirm('Are you sure you want to delete Build #' + buildNum + ' and its report?')) {
                fetch('/api/delete/' + buildNum, { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            location.reload();
                        } else {
                            alert('Failed to delete: ' + data.error);
                        }
                    });
            }
        }
    </script>
</body>
</html>
'''

HELP_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Help & Documentation - CNV Health</title>
    <meta charset="UTF-8">
    <style>''' + BASE_CSS + '''
    .markdown-body {
        max-width: 1000px;
        margin: 0 auto;
        padding: 20px;
        line-height: 1.7;
    }
    .markdown-body h1 { 
        font-size: 2.5em; 
        border-bottom: 2px solid var(--accent); 
        padding-bottom: 15px;
        margin-top: 30px;
    }
    .markdown-body h2 { 
        font-size: 1.8em; 
        border-bottom: 1px solid var(--border); 
        padding-bottom: 10px;
        margin-top: 40px;
        color: var(--accent);
    }
    .markdown-body h3 { 
        font-size: 1.4em; 
        margin-top: 25px;
        color: var(--text-primary);
    }
    .markdown-body table {
        width: 100%;
        border-collapse: collapse;
        margin: 20px 0;
    }
    .markdown-body th, .markdown-body td {
        border: 1px solid var(--border);
        padding: 12px 15px;
        text-align: left;
    }
    .markdown-body th {
        background: var(--bg-tertiary);
        font-weight: 600;
    }
    .markdown-body tr:hover {
        background: var(--bg-tertiary);
    }
    .markdown-body code {
        background: var(--bg-tertiary);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: monospace;
    }
    .markdown-body pre {
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 15px;
        border-radius: 8px;
        overflow-x: auto;
    }
    .markdown-body pre code {
        background: none;
        padding: 0;
    }
    .markdown-body ul, .markdown-body ol {
        padding-left: 25px;
        margin: 15px 0;
    }
    .markdown-body li {
        margin: 8px 0;
    }
    .markdown-body blockquote {
        border-left: 4px solid var(--accent);
        padding-left: 15px;
        margin: 20px 0;
        color: var(--text-secondary);
    }
    .markdown-body hr {
        border: none;
        border-top: 2px solid var(--border);
        margin: 30px 0;
    }
    .markdown-body img {
        max-width: 100%;
    }
    .feature-box {
        background: linear-gradient(135deg, var(--accent) 0%, #3399ff 100%);
        color: white;
        padding: 25px;
        border-radius: 12px;
        margin: 20px 0;
    }
    .feature-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 20px;
        margin: 20px 0;
    }
    .feature-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 20px;
    }
    .feature-card h4 {
        margin-top: 0;
        color: var(--accent);
    }
    .toc {
        background: var(--bg-tertiary);
        padding: 20px;
        border-radius: 10px;
        margin: 20px 0;
    }
    .toc ul {
        list-style: none;
        padding-left: 0;
    }
    .toc li {
        padding: 5px 0;
    }
    .toc a {
        color: var(--accent);
        text-decoration: none;
    }
    .toc a:hover {
        text-decoration: underline;
    }
    .badge-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        justify-content: center;
        margin: 20px 0;
    }
    .badge {
        display: inline-block;
        padding: 5px 12px;
        border-radius: 5px;
        font-size: 12px;
        font-weight: 600;
        color: white;
    }
    .badge-red { background: #EE0000; }
    .badge-blue { background: #3776AB; }
    .badge-black { background: #333; }
    .badge-purple { background: #6a1b9a; }
    .badge-orange { background: #FF6F00; }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">
                <div class="logo-img">🔍</div>
                <span class="logo-text">CNV Health Dashboard</span>
            </a>
            <nav class="header-nav">
                <a href="/">Dashboard</a>
                <a href="/job/configure">New Build</a>
                <a href="/job/history">Build History</a>
                <a href="/help" class="active">Help</a>
            </nav>
        </div>
    </header>
    
    <div class="breadcrumb">
        <a href="/">Dashboard</a>
        <span>›</span>
        <span>Help & Documentation</span>
    </div>
    
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-title">Documentation</div>
                <a href="#overview" class="sidebar-item active">
                    <span class="sidebar-icon">📖</span>
                    Overview
                </a>
                <a href="#key-innovations" class="sidebar-item">
                    <span class="sidebar-icon">🚀</span>
                    Key Innovations
                </a>
                <a href="#ai-evolution" class="sidebar-item">
                    <span class="sidebar-icon">🧠</span>
                    Self-Evolving AI
                </a>
                <a href="#performance" class="sidebar-item">
                    <span class="sidebar-icon">⚡</span>
                    Performance Engineering
                </a>
                <a href="#architecture" class="sidebar-item">
                    <span class="sidebar-icon">🏗️</span>
                    Architecture
                </a>
                <a href="#health-checks" class="sidebar-item">
                    <span class="sidebar-icon">🏥</span>
                    Health Checks
                </a>
                <a href="#configuration" class="sidebar-item">
                    <span class="sidebar-icon">⚙️</span>
                    Configuration
                </a>
            </div>
        </aside>
        
        <main class="main">
            <div class="markdown-body">
                <!-- Header -->
                <div style="text-align:center;margin-bottom:30px;">
                    <div class="badge-row">
                        <span class="badge badge-red">OpenShift</span>
                        <span class="badge badge-blue">Python</span>
                        <span class="badge badge-black">Flask</span>
                        <span class="badge badge-purple">KubeVirt</span>
                        <span class="badge badge-orange">AI Powered</span>
                    </div>
                    <h1 style="border:none;margin-top:20px;">🔍 CNV Health Crew</h1>
                    <p style="font-size:1.2em;color:var(--text-secondary);">
                        <strong>AI-Powered Performance Engineering & Health Monitoring</strong>
                    </p>
                    <p style="font-style:italic;color:var(--accent);">
                        🧠 Self-Evolving AI that Learns from Bugs, Emails & the Web
                    </p>
                </div>
                
                <hr>
                
                <!-- Key Innovations -->
                <h2 id="key-innovations">🚀 Key Innovations</h2>
                
                <div class="feature-grid">
                    <div class="feature-card" style="background:linear-gradient(135deg,#4527a0,#311b92);color:white;">
                        <h4 style="color:white;">🧠 Self-Evolving AI</h4>
                        <p><strong>The system learns from multiple sources:</strong></p>
                        <ul>
                            <li>🎫 <strong>Jira Bugs</strong> - Discovers new tests from bug reports</li>
                            <li>📧 <strong>Email</strong> - Learns from team discussions & alerts</li>
                            <li>🌐 <strong>Web</strong> - Searches docs, forums & knowledge bases</li>
                            <li>🎯 <strong>Patterns</strong> - Recognizes recurring issues</li>
                            <li>♾️ <strong>Never stops</strong> - Gets smarter with every run</li>
                        </ul>
                    </div>
                    <div class="feature-card" style="background:linear-gradient(135deg,#b71c1c,#880e4f);color:white;">
                        <h4 style="color:white;">⚡ Performance Engineering</h4>
                        <p><strong>Built for Performance Engineers:</strong></p>
                        <ul>
                            <li>📊 <strong>Resource profiling</strong> - CPU, Memory, I/O per node</li>
                            <li>🔥 <strong>Bottleneck detection</strong> - Find hotspots instantly</li>
                            <li>📈 <strong>Trend analysis</strong> - Track performance over time</li>
                            <li>⚠️ <strong>Threshold alerts</strong> - Proactive warnings at 85%+</li>
                            <li>🎯 <strong>Root cause analysis</strong> - AI-powered investigation</li>
                        </ul>
                    </div>
                </div>
                
                <hr>
                
                <!-- How AI Evolves -->
                <h2 id="ai-evolution">🔄 How the AI Evolves</h2>
                
                <div class="feature-box">
                    <h3 style="margin-top:0;text-align:center;">🧬 CONTINUOUS LEARNING CYCLE</h3>
                    <p style="text-align:center;opacity:0.9;">The system automatically improves with every run</p>
                </div>
                
                <table>
                    <tr>
                        <th style="text-align:center;">1️⃣ Gather Intel</th>
                        <th style="text-align:center;">2️⃣ Analyze</th>
                        <th style="text-align:center;">3️⃣ Suggest Tests</th>
                        <th style="text-align:center;">4️⃣ Auto-Add</th>
                        <th style="text-align:center;">5️⃣ Evolve</th>
                    </tr>
                    <tr>
                        <td style="text-align:center;">📥<br>🎫 Jira bugs<br>📧 Emails<br>🌐 Web docs</td>
                        <td style="text-align:center;">🔍<br>AI identifies patterns & recurring issues</td>
                        <td style="text-align:center;">💡<br>Proposes new health checks to add</td>
                        <td style="text-align:center;">✅<br>Approved tests join the suite</td>
                        <td style="text-align:center;">🧠<br>Knowledge grows continuously</td>
                    </tr>
                </table>
                
                <h3>🎯 Real Example of AI Evolution</h3>
                <pre><code>📥 Jira Bug: CNV-75962 "kubevirt-migration-controller OOMKilled at scale"

🤖 AI Analysis:
   ├─ Pattern detected: "OOMKilled" + "migration" + "scale"
   ├─ Component: kubevirt-migration-controller
   └─ Priority: Critical

💡 AI Suggestion:
   "Add new health check: migration_controller_memory"
   - Monitor memory usage of migration controller pods
   - Alert when approaching limits
   - Track during large-scale migrations

✅ Result: New test automatically added to suite!</code></pre>
                
                <hr>
                
                <!-- Health Checks -->
                <h2 id="health-checks">🏥 Health Checks</h2>
                
                <table>
                    <tr>
                        <th>Category</th>
                        <th>Checks</th>
                        <th>Status Indicators</th>
                    </tr>
                    <tr>
                        <td>🏗️ <strong>Infrastructure</strong></td>
                        <td>Nodes, Cluster Operators, etcd, MachineConfigPools</td>
                        <td>Ready/NotReady, Available/Degraded</td>
                    </tr>
                    <tr>
                        <td>📦 <strong>Workloads</strong></td>
                        <td>Pods (CrashLoop, Pending, OOM, Unknown)</td>
                        <td>Running/Failed/Pending</td>
                    </tr>
                    <tr>
                        <td>💻 <strong>Virtualization</strong></td>
                        <td>KubeVirt, VMs, VMIs, Migrations, virt-handler</td>
                        <td>Running/Stopped/Failed/Migrating</td>
                    </tr>
                    <tr>
                        <td>💾 <strong>Storage</strong></td>
                        <td>PVCs, CSI, DataVolumes, VolumeSnapshots, ODF</td>
                        <td>Bound/Pending/Ready</td>
                    </tr>
                    <tr>
                        <td>📊 <strong>Performance</strong></td>
                        <td>CPU, Memory, I/O per node</td>
                        <td>% utilization thresholds</td>
                    </tr>
                    <tr>
                        <td>🚨 <strong>Monitoring</strong></td>
                        <td>Prometheus alerts</td>
                        <td>Firing/Pending/Resolved</td>
                    </tr>
                </table>
                
                <hr>
                
                <!-- Performance Engineering -->
                <h2 id="performance">📊 Performance Engineering</h2>
                
                <div class="feature-grid">
                    <div class="feature-card">
                        <h4>🔥 What We Monitor</h4>
                        <table>
                            <tr><th>Metric</th><th>Threshold</th></tr>
                            <tr><td>CPU Usage</td><td>>85% ⚠️</td></tr>
                            <tr><td>Memory Pressure</td><td>>80% ⚠️</td></tr>
                            <tr><td>Disk I/O Latency</td><td>>100ms ⚠️</td></tr>
                            <tr><td>etcd Latency</td><td>>100ms 🔴</td></tr>
                            <tr><td>Pod Density</td><td>>50/node ⚠️</td></tr>
                        </table>
                    </div>
                    <div class="feature-card">
                        <h4>📈 AI-Powered Insights</h4>
                        <ul>
                            <li>🎯 Identifies resource hogs</li>
                            <li>🎯 Predicts capacity issues</li>
                            <li>🎯 Recommends optimizations</li>
                            <li>🎯 Tracks degradation trends</li>
                        </ul>
                        <h4>Actionable Reports:</h4>
                        <ul>
                            <li>"Node X is 92% CPU - spread VMs"</li>
                            <li>"Migration controller needs more memory"</li>
                            <li>"etcd on slow disk - SSD recommended"</li>
                        </ul>
                    </div>
                </div>
                
                <hr>
                
                <!-- Architecture -->
                <h2 id="architecture">🏗️ Architecture</h2>
                
                <table>
                    <tr><th colspan="4" style="background:#1a237e;color:white;text-align:center;">🌐 WEB DASHBOARD (Flask:5000)</th></tr>
                    <tr>
                        <td style="text-align:center;">🏠 Dashboard</td>
                        <td style="text-align:center;">⚙️ Configure</td>
                        <td style="text-align:center;">📋 History</td>
                        <td style="text-align:center;">📄 Reports</td>
                    </tr>
                    <tr><th colspan="4" style="background:#6a1b9a;color:white;text-align:center;">🧠 SELF-EVOLVING AI ENGINE</th></tr>
                    <tr>
                        <td style="text-align:center;">🎫 Jira Learning</td>
                        <td style="text-align:center;">📧 Email Learning</td>
                        <td style="text-align:center;">🌐 Web Learning</td>
                        <td style="text-align:center;">🧠 Knowledge Base</td>
                    </tr>
                    <tr><th colspan="4" style="background:#2e7d32;color:white;text-align:center;">⚡ PERFORMANCE ENGINE</th></tr>
                    <tr>
                        <td style="text-align:center;">📊 Resource Profiler</td>
                        <td style="text-align:center;">🔥 Bottleneck Detector</td>
                        <td style="text-align:center;">📈 Trend Analyzer</td>
                        <td style="text-align:center;">⚠️ Alert Engine</td>
                    </tr>
                    <tr><th colspan="4" style="background:#c62828;color:white;text-align:center;">☸️ OPENSHIFT CLUSTER</th></tr>
                    <tr>
                        <td style="text-align:center;">🖥️ Nodes</td>
                        <td style="text-align:center;">📦 Pods</td>
                        <td style="text-align:center;">💻 VMs</td>
                        <td style="text-align:center;">💾 Storage</td>
                    </tr>
                </table>
                
                <hr>
                
                <!-- Configuration -->
                <h2 id="configuration">⚙️ Configuration</h2>
                
                <h3>Environment Variables</h3>
                <table>
                    <tr><th>Variable</th><th>Description</th><th>Example</th></tr>
                    <tr><td><code>RH_LAB_HOST</code></td><td>SSH target hostname</td><td>host.example.com</td></tr>
                    <tr><td><code>RH_LAB_USER</code></td><td>SSH username</td><td>root</td></tr>
                    <tr><td><code>SSH_KEY_PATH</code></td><td>Path to SSH private key</td><td>~/.ssh/id_rsa</td></tr>
                </table>
                
                <h3>Command Line Options</h3>
                <table>
                    <tr><th>Flag</th><th>Description</th></tr>
                    <tr><td><code>--server &lt;host&gt;</code></td><td>Override SSH target</td></tr>
                    <tr><td><code>--ai</code></td><td>Enable full AI root cause analysis</td></tr>
                    <tr><td><code>--rca-bugs</code></td><td>Bug matching only (faster)</td></tr>
                    <tr><td><code>--rca-jira</code></td><td>Search Jira for related bugs</td></tr>
                    <tr><td><code>--check-jira</code></td><td><strong>Enable AI evolution</strong> - scan for new tests</td></tr>
                    <tr><td><code>--email</code></td><td>Send report via email</td></tr>
                </table>
                
                <hr>
                
                <!-- Quick Start -->
                <h2 id="overview">⚡ Quick Start</h2>
                
                <pre><code># 1️⃣ Configure credentials
nano .env
# Set: RH_LAB_HOST, RH_LAB_USER, SSH_KEY_PATH

# 2️⃣ Start Dashboard
./start_dashboard.sh

# 3️⃣ Open Browser → http://localhost:5000

# 4️⃣ Run with AI Evolution enabled
# Select "Full RCA" + "Jira Integration" in the UI</code></pre>
                
                <hr>
                
                <p style="text-align:center;color:var(--text-secondary);margin-top:40px;">
                    <strong>🧠 AI-Powered • ⚡ Performance Focused • 🔄 Self-Evolving</strong><br>
                    Built with ❤️ for Performance Engineers & SRE Teams
                </p>
            </div>
        </main>
    </div>
</body>
</html>
'''

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/help')
def help_page():
    """Help and documentation page"""
    return render_template_string(HELP_HTML)

@app.route('/')
def dashboard():
    """Main dashboard"""
    load_builds()
    
    # Get running build if any
    running_build = None
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        running_build = running_jobs[job_id]
    
    # Calculate stats
    stats = {
        'total': len(builds),
        'success': sum(1 for b in builds if b.get('status') == 'success'),
        'unstable': sum(1 for b in builds if b.get('status') == 'unstable'),
        'failed': sum(1 for b in builds if b.get('status') == 'failed')
    }
    
    return render_template_string(DASHBOARD_HTML,
                                  builds=builds[:10],
                                  recent_builds=builds[:10],
                                  stats=stats,
                                  running_build=running_build)

@app.route('/job/configure')
def configure():
    """Build configuration page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    preset = request.args.get('preset', '')  # 'all' for quick build
    return render_template_string(CONFIGURE_HTML,
                                  checks=AVAILABLE_CHECKS,
                                  categories=categories,
                                  preset=preset)

@app.route('/job/run', methods=['POST'])
def run_build():
    """Start a new build"""
    # Get selected checks
    selected_checks = request.form.getlist('checks')
    if not selected_checks:
        selected_checks = list(AVAILABLE_CHECKS.keys())
    
    # Get RCA level: none, bugs, full
    rca_level = request.form.get('rca_level', 'none')
    
    options = {
        'server_host': request.form.get('server_host', '').strip(),
        'rca_level': rca_level,
        'rca_jira': 'rca_jira' in request.form,
        'rca_email': 'rca_email' in request.form,
        'rca_web': 'rca_web' in request.form,
        'jira': 'check_jira' in request.form,
        'email': 'send_email' in request.form,
        'email_to': request.form.get('email_to', 'guchen@redhat.com')
    }
    
    # Start the build
    start_build(selected_checks, options)
    
    return redirect(url_for('dashboard'))

@app.route('/job/quick-run')
def quick_run():
    """Quick build - redirect to configure with all checks selected"""
    return redirect(url_for('configure') + '?preset=all')

@app.route('/job/history')
def history():
    """Build history page"""
    load_builds()
    status_filter = request.args.get('status')
    
    filtered_builds = builds
    if status_filter:
        filtered_builds = [b for b in builds if b.get('status') == status_filter]
    
    return render_template_string(HISTORY_HTML, builds=filtered_builds)

@app.route('/job/<int:build_num>')
def build_detail(build_num):
    """Build detail page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if not build:
        # Check if it's currently running
        if running_jobs:
            job_id = list(running_jobs.keys())[0]
            if running_jobs[job_id].get('number') == build_num:
                build = running_jobs[job_id]
    
    if not build:
        return "Build not found", 404
    
    return render_template_string(BUILD_DETAIL_HTML, build=build, checks=AVAILABLE_CHECKS)

@app.route('/job/<int:build_num>/console')
def console_output(build_num):
    """Console output page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if not build and running_jobs:
        job_id = list(running_jobs.keys())[0]
        if running_jobs[job_id].get('number') == build_num:
            build = running_jobs[job_id]
    
    if not build:
        return "Build not found", 404
    
    return render_template_string(CONSOLE_HTML, build=build)

@app.route('/job/rebuild/<int:build_num>')
def rebuild(build_num):
    """Rebuild with same parameters"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if build:
        checks = build.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = build.get('options', {'rca_level': 'none', 'jira': False, 'email': False})
        start_build(checks, options)
    
    return redirect(url_for('dashboard'))

@app.route('/report/<filename>')
def serve_report(filename):
    """Serve report files"""
    return send_from_directory(REPORTS_DIR, filename)

@app.route('/api/status')
def api_status():
    """API endpoint for build status"""
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        job = running_jobs[job_id]
        return jsonify({
            'running': True,
            'output': job.get('output', ''),
            'progress': job.get('progress', 0),
            'phases': job.get('phases', []),
            'current_phase': job.get('current_phase', '')
        })
    return jsonify({'running': False})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """API endpoint to stop running build"""
    global builds
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        job = running_jobs[job_id]
        
        try:
            # Kill the process and all its children
            process = job.get('process')
            if process and process.poll() is None:
                try:
                    # Kill entire process group (includes all child processes)
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # Force kill if SIGTERM didn't work
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=2)
                except (ProcessLookupError, OSError):
                    # Process already dead or no permission
                    pass
            
            # Mark as stopped
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] ⛔ Build stopped by user\n'
            job['current_phase'] = 'Stopped by user'
            
            # Mark current phase as error
            for phase in job.get('phases', []):
                if phase['status'] == 'running':
                    phase['status'] = 'error'
            
            # Save to builds as cancelled
            duration_secs = int(time.time() - job['start_time'])
            duration = f"{duration_secs // 60}m {duration_secs % 60}s"
            
            build_record = {
                'number': job['number'],
                'status': 'failed',
                'status_text': 'Stopped',
                'checks': job.get('checks', []),
                'checks_count': job.get('checks_count', 0),
                'options': job.get('options', {}),
                'timestamp': job['timestamp'],
                'duration': duration,
                'output': job['output'],
                'report_file': None
            }
            
            builds.insert(0, build_record)
            save_builds()
            
            # Remove from running
            del running_jobs[job_id]
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    return jsonify({'success': False, 'error': 'No running build'})

@app.route('/api/delete/<int:build_num>', methods=['POST'])
def api_delete(build_num):
    """API endpoint to delete a build and its report"""
    global builds
    load_builds()
    
    try:
        # Find the build
        build = next((b for b in builds if b.get('number') == build_num), None)
        
        if not build:
            return jsonify({'success': False, 'error': 'Build not found'})
        
        # Delete the report file if it exists
        report_file = build.get('report_file')
        if report_file:
            report_path = os.path.join(REPORTS_DIR, report_file)
            if os.path.exists(report_path):
                os.remove(report_path)
            # Also try to delete the .md version
            md_file = report_file.replace('.html', '.md')
            md_path = os.path.join(REPORTS_DIR, md_file)
            if os.path.exists(md_path):
                os.remove(md_path)
        
        # Remove from builds list
        builds = [b for b in builds if b.get('number') != build_num]
        save_builds()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============================================================================
# BUILD EXECUTION
# ============================================================================

def start_build(checks, options):
    """Start a new build"""
    global builds
    
    if running_jobs:
        return  # Already running
    
    build_num = get_next_build_number()
    job_id = f"build_{build_num}"
    
    # Build command
    cmd = [sys.executable, SCRIPT_PATH]
    
    # Server host
    server_host = options.get('server_host', '')
    if server_host:
        cmd.extend(['--server', server_host])
    
    # RCA level handling: none, bugs, full
    rca_level = options.get('rca_level', 'none')
    if rca_level == 'bugs':
        cmd.append('--rca-bugs')
    elif rca_level == 'full':
        cmd.append('--ai')
    
    # RCA sources
    if options.get('rca_jira'):
        cmd.append('--rca-jira')
    if options.get('rca_email'):
        cmd.append('--rca-email')
    
    if options.get('jira'):
        cmd.append('--check-jira')
    if options.get('email'):
        cmd.append('--email')
    
    # Define phases based on RCA level and sources
    phases = [
        {'name': 'Initialize', 'status': 'pending'},
        {'name': 'Connect', 'status': 'pending'},
        {'name': 'Collect Data', 'status': 'pending'},
        {'name': 'Analyze', 'status': 'pending'},
        {'name': 'Generate Report', 'status': 'pending'},
    ]
    
    # Insert RCA phases based on level and sources
    rca_phase_idx = 4
    if rca_level != 'none':
        if options.get('rca_jira'):
            phases.insert(rca_phase_idx, {'name': 'Search Jira', 'status': 'pending'})
            rca_phase_idx += 1
        if options.get('rca_email'):
            phases.insert(rca_phase_idx, {'name': 'Search Email', 'status': 'pending'})
            rca_phase_idx += 1
        if options.get('rca_web'):
            phases.insert(rca_phase_idx, {'name': 'Search Web', 'status': 'pending'})
            rca_phase_idx += 1
        if rca_level == 'full':
            phases.insert(rca_phase_idx, {'name': 'Deep RCA', 'status': 'pending'})
    
    if options.get('email'):
        phases.append({'name': 'Send Email', 'status': 'pending'})
    
    # Initialize running job
    running_jobs[job_id] = {
        'number': build_num,
        'status': 'running',
        'status_text': 'Running',
        'output': f'[{datetime.now().strftime("%H:%M:%S")}] Starting build #{build_num}...\n',
        'checks': checks,
        'checks_count': len(checks),
        'options': options,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'start_time': time.time(),
        'progress': 5,
        'phases': phases,
        'current_phase': 'Initializing...'
    }
    
    def set_phase(job, index, status, phase_name=None):
        """Update phase status"""
        if index < len(job['phases']):
            job['phases'][index]['status'] = status
        if phase_name:
            job['current_phase'] = phase_name
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ▶ {phase_name}\n'
    
    def run_job():
        job = running_jobs[job_id]
        report_file = None
        
        try:
            # Phase 0: Initialize
            set_phase(job, 0, 'running', 'Initializing build environment...')
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Options: AI={options.get("ai")}, Jira={options.get("jira")}, Email={options.get("email")}\n'
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Checks: {len(checks)} selected\n'
            job['output'] += '-' * 60 + '\n'
            job['progress'] = 5
            set_phase(job, 0, 'done')
            
            # Phase 1: Connect
            set_phase(job, 1, 'running', 'Connecting to cluster...')
            job['progress'] = 10
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                cwd=BASE_DIR,
                bufsize=1,
                start_new_session=True  # Create new process group for clean termination
            )
            
            # Store process in job for stop functionality
            job['process'] = process
            
            # Track phases based on output
            stdout_lines = []
            current_phase_idx = 1
            # Calculate phase offsets based on RCA level and sources
            rca_level = options.get('rca_level', 'none')
            rca_phases = 0
            if rca_level != 'none':
                if options.get('rca_jira'):
                    rca_phases += 1
                if options.get('rca_email'):
                    rca_phases += 1
                if options.get('rca_web'):
                    rca_phases += 1
                if rca_level == 'full':
                    rca_phases += 1  # Deep RCA
            
            phase_keywords = {
                'Connecting': (1, 'Connecting to cluster...', 15),
                'Collecting': (2, 'Collecting health data...', 25),
                'collected': (2, 'Data collection complete', 50),
                'Analyzing': (3, 'Analyzing results...', 60),
                'Searching Jira': (4 if options.get('rca_jira') and rca_level != 'none' else -1, 'Searching Jira for bugs...', 62),
                'Searching email': (4 + (1 if options.get('rca_jira') else 0) if options.get('rca_email') and rca_level != 'none' else -1, 'Searching emails...', 65),
                'Searching web': (4 + (1 if options.get('rca_jira') else 0) + (1 if options.get('rca_email') else 0) if options.get('rca_web') and rca_level != 'none' else -1, 'Searching web docs...', 68),
                'deep investigation': (4 + rca_phases - 1 if rca_level == 'full' else -1, 'Running deep RCA...', 70),
                'Analysis': (4 + rca_phases, 'Running analysis...', 70),
                'Generating': (4 + rca_phases, 'Generating report...', 80),
                'Report saved': (4 + rca_phases, 'Report generated', 85),
                'Sending': (len(phases)-1 if options.get('email') else -1, 'Sending email...', 90),
                'Email sent': (len(phases)-1 if options.get('email') else -1, 'Email sent', 95),
            }
            
            # Handle jira interactive prompt
            if options.get('jira'):
                process.stdin.write("skip\n")
                process.stdin.flush()
            
            # Read output line by line for real-time updates
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    stdout_lines.append(line)
                    job['output'] += line
                    
                    # Check for phase keywords
                    for keyword, (phase_idx, phase_msg, progress) in phase_keywords.items():
                        if keyword in line and phase_idx >= 0:
                            if phase_idx > current_phase_idx:
                                # Mark previous phases as done
                                for i in range(current_phase_idx, phase_idx):
                                    set_phase(job, i, 'done')
                                current_phase_idx = phase_idx
                            set_phase(job, phase_idx, 'running', phase_msg)
                            job['progress'] = progress
                            break
            
            process.wait(timeout=60)
            stdout = ''.join(stdout_lines)
            
            # Mark remaining phases as done
            for i in range(current_phase_idx, len(phases)):
                set_phase(job, i, 'done')
            job['progress'] = 95
            
            # Find the generated report
            html_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "health_report_*.html")), reverse=True)
            if html_files:
                report_file = os.path.basename(html_files[0])
            
            # Determine status
            if process.returncode != 0:
                status = 'failed'
                status_text = 'Failed'
            elif 'ATTENTION NEEDED' in stdout or '❌' in stdout:
                status = 'unstable'
                status_text = 'Issues Found'
            else:
                status = 'success'
                status_text = 'Success'
            
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] Build finished with status: {status_text}\n'
            job['progress'] = 100
            
        except subprocess.TimeoutExpired:
            status = 'failed'
            status_text = 'Timeout'
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] Build timed out after 5 minutes\n'
        except Exception as e:
            status = 'failed'
            status_text = 'Error'
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] Error: {str(e)}\n'
        
        # Calculate duration
        duration_secs = int(time.time() - job['start_time'])
        duration = f"{duration_secs // 60}m {duration_secs % 60}s"
        
        # Save to builds list
        build_record = {
            'number': build_num,
            'status': status,
            'status_text': status_text,
            'checks': checks,
            'checks_count': len(checks),
            'options': options,
            'timestamp': job['timestamp'],
            'duration': duration,
            'output': job['output'],
            'report_file': report_file
        }
        
        builds.insert(0, build_record)
        save_builds()
        
        # Clean up running job
        del running_jobs[job_id]
    
    thread = threading.Thread(target=run_job)
    thread.start()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  🔍 CNV Health Dashboard")
    print("=" * 60)
    print(f"\n  Open in browser: http://localhost:5000")
    print(f"\n  Press Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
