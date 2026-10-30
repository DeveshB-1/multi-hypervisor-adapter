from unittest.mock import MagicMock, patch
import pytest

from hypervisor_adapter import LibvirtKvmAdapter, PowerState, VMCreateRequest, VMResizeRequest
from hypervisor_adapter.base import VMNotFoundError


@pytest.fixture
def mock_libvirt():
    with patch("hypervisor_adapter.libvirt_kvm.libvirt") as mock_lib:
        mock_conn = MagicMock()
        mock_lib.open.return_value = mock_conn
        mock_conn.isAlive.return_value = 1
        yield mock_lib, mock_conn


def test_libvirt_ping(mock_libvirt):
    mock_lib, mock_conn = mock_libvirt
    adapter = LibvirtKvmAdapter(uri="qemu:///session")
    assert adapter.ping() is True


def test_libvirt_list_vms(mock_libvirt):
    mock_lib, mock_conn = mock_libvirt
    mock_dom1 = MagicMock()
    mock_dom1.name.return_value = "local-vm-01"
    mock_dom1.UUIDString.return_value = "uuid-1111"
    mock_dom1.state.return_value = [1, 0]  # VIR_DOMAIN_RUNNING = 1
    mock_dom1.XMLDesc.return_value = "<domain><vcpu>4</vcpu><memory unit='KiB'>8388608</memory></domain>"

    mock_conn.listAllDomains.return_value = [mock_dom1]

    adapter = LibvirtKvmAdapter(uri="qemu:///session")
    vms = adapter.list_vms()
    assert len(vms) == 1
    assert vms[0].name == "local-vm-01"
    assert vms[0].status == PowerState.RUNNING
    assert vms[0].cpu_cores == 4
    assert vms[0].memory_mb == 8192


def test_libvirt_start_stop(mock_libvirt):
    mock_lib, mock_conn = mock_libvirt
    mock_dom = MagicMock()
    mock_dom.name.return_value = "local-vm-01"
    mock_dom.UUIDString.return_value = "uuid-1111"
    mock_dom.isActive.return_value = 0
    mock_conn.lookupByUUIDString.return_value = mock_dom

    adapter = LibvirtKvmAdapter(uri="qemu:///session")
    
    # Start
    start_res = adapter.start_vm("uuid-1111")
    assert start_res.status == "completed"
    mock_dom.create.assert_called_once()

    # Stop
    mock_dom.isActive.return_value = 1
    stop_res = adapter.stop_vm("uuid-1111", force=True)
    assert stop_res.status == "completed"
    mock_dom.destroy.assert_called_once()


def test_libvirt_resize(mock_libvirt):
    mock_lib, mock_conn = mock_libvirt
    mock_dom = MagicMock()
    mock_dom.name.return_value = "local-vm-01"
    mock_dom.UUIDString.return_value = "uuid-1111"
    mock_dom.isActive.return_value = 1
    mock_conn.lookupByUUIDString.return_value = mock_dom

    adapter = LibvirtKvmAdapter(uri="qemu:///session")
    res = adapter.resize_vm("uuid-1111", VMResizeRequest(cpu_cores=8, memory_mb=16384))
    assert res.status == "completed"
    mock_dom.setMemory.assert_called_once_with(16384 * 1024)
