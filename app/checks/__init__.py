"""
Health Check Metadata

Re-exports AVAILABLE_CHECKS from config.settings — the list of check categories
that can be selected in the dashboard (Nodes, Operators, Pods, KubeVirt, etc.).

The actual check logic lives in healthchecks/hybrid_health_check.py.
"""

from config.settings import AVAILABLE_CHECKS

__all__ = ['AVAILABLE_CHECKS']
