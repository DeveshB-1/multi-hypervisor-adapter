from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from hypervisor_adapter.models import (
    HypervisorType,
    TaskResult,
    VMCreateRequest,
    VMInfo,
    VMResizeRequest,
)


class HypervisorError(Exception):
    """Base exception for all hypervisor adapter errors."""
    pass


class HypervisorAuthError(HypervisorError):
    """Raised when authentication credentials or token are invalid."""
    pass


class VMNotFoundError(HypervisorError):
    """Raised when the requested virtual machine does not exist."""
    pass


class HypervisorConnectionError(HypervisorError):
    """Raised when network connection to the hypervisor endpoint fails."""
    pass


class TaskTimeoutError(HypervisorError):
    """Raised when an asynchronous task does not finish within the deadline."""
    pass


class BaseComputeAdapter(ABC):
    """
    Abstract interface for compute hypervisors.
    Any virtualization backend (Proxmox, VMware, Hyper-V, KVM) must implement this.
    """

    def __init__(self, endpoint: str, verify_ssl: bool = False, timeout: int = 30) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    @property
    @abstractmethod
    def hypervisor_type(self) -> HypervisorType:
        """Returns the specific hypervisor type."""
        pass

    @abstractmethod
    def ping(self) -> bool:
        """Checks connectivity and credential validity against the hypervisor."""
        pass

    @abstractmethod
    def list_vms(self) -> List[VMInfo]:
        """Lists all virtual machines managed by this cluster or host."""
        pass

    @abstractmethod
    def get_vm(self, vm_id: str) -> VMInfo:
        """Retrieves details of a specific virtual machine."""
        pass

    @abstractmethod
    def start_vm(self, vm_id: str) -> TaskResult:
        """Powers on a virtual machine."""
        pass

    @abstractmethod
    def stop_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        """Powers off a virtual machine (graceful ACPI shutdown by default, hard stop if force=True)."""
        pass

    @abstractmethod
    def restart_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        """Reboots a virtual machine."""
        pass

    @abstractmethod
    def create_vm(self, request: VMCreateRequest) -> TaskResult:
        """Deploys a new virtual machine by cloning a template image."""
        pass

    @abstractmethod
    def resize_vm(self, vm_id: str, request: VMResizeRequest) -> TaskResult:
        """Modifies vCPU or memory allocations of a virtual machine."""
        pass

    @abstractmethod
    def delete_vm(self, vm_id: str) -> TaskResult:
        """Permanently deletes a virtual machine and its attached disks."""
        pass
