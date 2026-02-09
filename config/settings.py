"""
CNV HealthCrew AI - Configuration Settings

Supports two modes:
  - Dev mode:  Reads .env from project root, stores data locally
  - Installed:  Reads ~/.config/cnv-healthcrew/config.env, stores in XDG dirs
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load config: installed path first, then fall back to local .env
_INSTALLED_CONFIG = Path.home() / ".config" / "cnv-healthcrew" / "config.env"
if _INSTALLED_CONFIG.exists():
    load_dotenv(_INSTALLED_CONFIG)
else:
    load_dotenv()  # loads .env from cwd


def _xdg_data_dir():
    """Get XDG data directory for installed mode"""
    return Path.home() / ".local" / "share" / "cnv-healthcrew"


def _is_installed():
    """Check if running in installed mode (config.env exists in XDG config dir)"""
    return _INSTALLED_CONFIG.exists()


class Config:
    """Application configuration"""
    
    # Base paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # In installed mode, use XDG directories; in dev mode, use project-local paths
    if _is_installed():
        DATA_DIR = str(_xdg_data_dir())
        REPORTS_DIR = str(_xdg_data_dir() / "reports")
        BUILDS_FILE = str(_xdg_data_dir() / "builds.json")
    else:
        DATA_DIR = BASE_DIR
        REPORTS_DIR = os.path.join(BASE_DIR, "reports")
        BUILDS_FILE = os.path.join(BASE_DIR, ".builds.json")
    
    TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
    STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
    
    # SSH Configuration
    SSH_HOST = os.getenv("RH_LAB_HOST")
    SSH_USER = os.getenv("RH_LAB_USER", "root")
    SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")
    KUBECONFIG = os.getenv("KUBECONFIG_REMOTE", "/home/kni/clusterconfigs/auth/kubeconfig")
    
    # Email Configuration
    DEFAULT_EMAIL = os.getenv("EMAIL_TO", "guchen@redhat.com")
    
    # Flask Configuration
    FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG = False
    
    # Build Configuration
    MAX_BUILDS_HISTORY = 100
    
    # Health Check Thresholds
    CPU_WARNING_THRESHOLD = 85
    MEMORY_WARNING_THRESHOLD = 80
    DISK_LATENCY_THRESHOLD_MS = 100
    ETCD_LATENCY_THRESHOLD_MS = 100
    POD_DENSITY_WARNING = 50
    
    # AI Configuration
    OLLAMA_MODEL = "ollama/llama3.2:3b"
    OLLAMA_URL = "http://localhost:11434"
    
    # Jira Configuration
    JIRA_PROJECTS = ["CNV", "OCPBUGS", "ODF"]
    JIRA_BUG_SCAN_DAYS = 30
    JIRA_BUG_LIMIT = 50


# Available health checks configuration
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
