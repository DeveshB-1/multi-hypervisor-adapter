from unittest.mock import MagicMock
import pytest

from hypervisor_adapter import (
    HypervisorType,
    MultiHypervisorClient,
    PowerState,
    VMInfo,
)


def test_multi_hypervisor_client():
    client = MultiHypervisorClient()

    mock_proxmox = MagicMock()
    mock_proxmox.hypervisor_type = HypervisorType.PROXMOX
    mock_proxmox.list_vms.return_value = [
        VMInfo(
            vm_id="101",
            name="pve-vm",
            status=PowerState.RUNNING,
            hypervisor=HypervisorType.PROXMOX,
            cpu_cores=2,
            memory_mb=4096,
        )
    ]

    mock_vmware = MagicMock()
    mock_vmware.hypervisor_type = HypervisorType.VMWARE
    mock_vmware.list_vms.return_value = [
        VMInfo(
            vm_id="vm-201",
            name="esxi-vm",
            status=PowerState.STOPPED,
            hypervisor=HypervisorType.VMWARE,
            cpu_cores=8,
            memory_mb=16384,
        )
    ]

    client.register("zone-pve", mock_proxmox)
    client.register("zone-vmw", mock_vmware)

    assert set(client.clusters) == {"zone-pve", "zone-vmw"}

    # Aggregate list
    all_vms = client.list_vms()
    assert len(all_vms) == 2
    assert all_vms[0].hypervisor == HypervisorType.PROXMOX
    assert all_vms[1].hypervisor == HypervisorType.VMWARE

    # Per-cluster list
    pve_vms = client.list_vms("zone-pve")
    assert len(pve_vms) == 1
    assert pve_vms[0].name == "pve-vm"

    # Action proxying
    client.start_vm("zone-pve", "101")
    mock_proxmox.start_vm.assert_called_once_with("101")

    client.stop_vm("zone-vmw", "vm-201", force=True)
    mock_vmware.stop_vm.assert_called_once_with("vm-201", force=True)
