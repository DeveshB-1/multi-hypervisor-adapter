"""
Multi-Hypervisor Adapter
A unified compute management adapter for Proxmox (KVM) and VMware vCenter REST APIs.
"""

from hypervisor_adapter.base import (
    BaseComputeAdapter,
    HypervisorAuthError,
    HypervisorConnectionError,
    HypervisorError,
    TaskTimeoutError,
    VMNotFoundError,
)
from hypervisor_adapter.client import MultiHypervisorClient
from hypervisor_adapter.models import (
    HypervisorType,
    PowerState,
    TaskResult,
    VMCreateRequest,
    VMInfo,
    VMResizeRequest,
)
from hypervisor_adapter.proxmox import ProxmoxAdapter
from hypervisor_adapter.vmware import VMwareAdapter

__version__ = "0.1.0"
__all__ = [
    "BaseComputeAdapter",
    "ProxmoxAdapter",
    "VMwareAdapter",
    "MultiHypervisorClient",
    "HypervisorType",
    "PowerState",
    "VMInfo",
    "VMCreateRequest",
    "VMResizeRequest",
    "TaskResult",
    "HypervisorError",
    "HypervisorAuthError",
    "VMNotFoundError",
    "HypervisorConnectionError",
    "TaskTimeoutError",
]
