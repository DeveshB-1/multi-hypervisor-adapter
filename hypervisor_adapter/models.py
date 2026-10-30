from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HypervisorType(str, Enum):
    PROXMOX = "proxmox"
    VMWARE = "vmware"
    KVM = "kvm"
    LIBVIRT = "libvirt"


class PowerState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class VMInfo(BaseModel):
    vm_id: str = Field(description="Unique identifier of the virtual machine")
    name: str = Field(description="Human-readable display name")
    status: PowerState = Field(default=PowerState.UNKNOWN, description="Current power state")
    hypervisor: HypervisorType = Field(description="Underlying hypervisor technology")
    cpu_cores: int = Field(default=1, description="Allocated vCPU cores")
    memory_mb: int = Field(default=1024, description="Allocated RAM in MiB")
    disk_gb: Optional[float] = Field(default=None, description="Primary disk capacity in GiB")
    ip_addresses: List[str] = Field(default_factory=list, description="Associated IP addresses")
    node: Optional[str] = Field(default=None, description="Physical node or host housing the VM")
    uptime_seconds: Optional[int] = Field(default=None, description="Uptime in seconds if running")
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Native hypervisor response")


class VMCreateRequest(BaseModel):
    name: str = Field(description="Display name for the newly provisioned VM")
    template_id: str = Field(description="ID/Name of the template/gold image to clone from")
    target_node: Optional[str] = Field(default=None, description="Specific target hypervisor node/host")
    cpu_cores: int = Field(default=2, ge=1, description="Number of vCPUs to allocate")
    memory_mb: int = Field(default=4096, ge=512, description="RAM in MiB")
    storage_pool: Optional[str] = Field(default=None, description="Target storage datastore or pool name")
    disk_gb: Optional[int] = Field(default=None, ge=10, description="Optional custom disk size in GiB")
    
    # Cloud-init / Guest Customization
    cloud_init_user: Optional[str] = Field(default="ubuntu", description="Default admin username")
    cloud_init_password: Optional[str] = Field(default=None, description="Default admin password")
    cloud_init_ssh_key: Optional[str] = Field(default=None, description="Public SSH key for passwordless login")
    ip_cidr: Optional[str] = Field(default=None, description="Static IP with CIDR (e.g., 10.10.1.50/24)")
    gateway: Optional[str] = Field(default=None, description="Default network gateway IP")


class VMResizeRequest(BaseModel):
    cpu_cores: Optional[int] = Field(default=None, ge=1, description="New vCPU core count")
    memory_mb: Optional[int] = Field(default=None, ge=512, description="New RAM in MiB")


class TaskResult(BaseModel):
    task_id: str = Field(description="Job or task identifier from the hypervisor")
    status: str = Field(description="Initial status (queued, running, completed)")
    message: str = Field(default="Operation accepted")
    vm_id: Optional[str] = Field(default=None, description="Affected VM ID if applicable")
