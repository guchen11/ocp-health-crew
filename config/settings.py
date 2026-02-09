"""
CNV HealthCrew AI - Configuration Settings
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration"""
    
    # Base paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    REPORTS_DIR = os.path.join(BASE_DIR, "reports")
    TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
    STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
    
    # SSH Configuration
    SSH_HOST = os.getenv("RH_LAB_HOST")
    SSH_USER = os.getenv("RH_LAB_USER", "root")
    SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")
    KUBECONFIG = "/home/kni/clusterconfigs/auth/kubeconfig"
    
    # Email Configuration
    DEFAULT_EMAIL = "guchen@redhat.com"
    
    # Flask Configuration
    FLASK_HOST = "0.0.0.0"
    FLASK_PORT = 5000
    FLASK_DEBUG = False
    
    # Build Configuration
    BUILDS_FILE = os.path.join(BASE_DIR, ".builds.json")
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
