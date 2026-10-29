from __future__ import annotations

import logging
from typing import Dict, List, Optional

from hypervisor_adapter.base import BaseComputeAdapter, HypervisorError
from hypervisor_adapter.models import (
    HypervisorType,
    TaskResult,
    VMCreateRequest,
    VMInfo,
    VMResizeRequest,
)

logger = logging.getLogger(__name__)


class MultiHypervisorClient:
    """
    Unified client facade for managing multiple heterogeneous hypervisor clusters.
    Allows registering multiple Proxmox (KVM) and VMware vCenter endpoints and
    operating on them with a single uniform API.
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, BaseComputeAdapter] = {}

    def register(self, cluster_name: str, adapter: BaseComputeAdapter) -> MultiHypervisorClient:
        """Register a hypervisor cluster adapter under a unique cluster name."""
        self._adapters[cluster_name] = adapter
        logger.info(f"Registered {adapter.hypervisor_type.value} adapter for cluster '{cluster_name}'")
        return self

    def unregister(self, cluster_name: str) -> None:
        """Remove a hypervisor adapter."""
        self._adapters.pop(cluster_name, None)

    def get_adapter(self, cluster_name: str) -> BaseComputeAdapter:
        """Retrieve an adapter by cluster name."""
        adapter = self._adapters.get(cluster_name)
        if not adapter:
            raise HypervisorError(
                f"Cluster '{cluster_name}' is not registered. Registered clusters: {list(self._adapters.keys())}"
            )
        return adapter

    @property
    def clusters(self) -> List[str]:
        """List all registered cluster names."""
        return list(self._adapters.keys())

    def list_vms(self, cluster_name: Optional[str] = None) -> List[VMInfo]:
        """
        List virtual machines.
        If cluster_name is provided, lists VMs in that cluster.
        If omitted, aggregates VMs across all registered clusters.
        """
        if cluster_name:
            return self.get_adapter(cluster_name).list_vms()

        all_vms: List[VMInfo] = []
        for name, adapter in self._adapters.items():
            try:
                vms = adapter.list_vms()
                all_vms.extend(vms)
            except Exception as e:
                logger.error(f"Error querying VMs from cluster '{name}': {e}")
        return all_vms

    def get_vm(self, cluster_name: str, vm_id: str) -> VMInfo:
        return self.get_adapter(cluster_name).get_vm(vm_id)

    def start_vm(self, cluster_name: str, vm_id: str) -> TaskResult:
        return self.get_adapter(cluster_name).start_vm(vm_id)

    def stop_vm(self, cluster_name: str, vm_id: str, force: bool = False) -> TaskResult:
        return self.get_adapter(cluster_name).stop_vm(vm_id, force=force)

    def restart_vm(self, cluster_name: str, vm_id: str, force: bool = False) -> TaskResult:
        return self.get_adapter(cluster_name).restart_vm(vm_id, force=force)

    def create_vm(self, cluster_name: str, request: VMCreateRequest) -> TaskResult:
        return self.get_adapter(cluster_name).create_vm(request)

    def resize_vm(self, cluster_name: str, vm_id: str, request: VMResizeRequest) -> TaskResult:
        return self.get_adapter(cluster_name).resize_vm(vm_id, request)

    def delete_vm(self, cluster_name: str, vm_id: str) -> TaskResult:
        return self.get_adapter(cluster_name).delete_vm(vm_id)
