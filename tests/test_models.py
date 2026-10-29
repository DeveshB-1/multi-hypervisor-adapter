import pytest
from hypervisor_adapter.models import (
    HypervisorType,
    PowerState,
    VMCreateRequest,
    VMInfo,
    VMResizeRequest,
)


def test_vminfo_model():
    vm = VMInfo(
        vm_id="vm-101",
        name="test-web",
        status=PowerState.RUNNING,
        hypervisor=HypervisorType.PROXMOX,
        cpu_cores=4,
        memory_mb=8192,
        disk_gb=100.0,
        node="pve-node1",
    )
    assert vm.vm_id == "vm-101"
    assert vm.status == PowerState.RUNNING
    assert vm.hypervisor == HypervisorType.PROXMOX
    assert vm.cpu_cores == 4
    assert vm.memory_mb == 8192


def test_vm_create_request_validation():
    req = VMCreateRequest(
        name="new-vm",
        template_id="tpl-ubuntu-24",
        cpu_cores=2,
        memory_mb=4096,
        cloud_init_user="root",
    )
    assert req.name == "new-vm"
    assert req.cpu_cores == 2
    assert req.memory_mb == 4096

    # Test validation error on invalid core count
    with pytest.raises(Exception):
        VMCreateRequest(name="bad", template_id="tpl", cpu_cores=0)


def test_vm_resize_request():
    req = VMResizeRequest(cpu_cores=8, memory_mb=16384)
    assert req.cpu_cores == 8
    assert req.memory_mb == 16384
