from unittest.mock import MagicMock, patch
import pytest

from hypervisor_adapter import VMwareAdapter, PowerState, VMResizeRequest
from hypervisor_adapter.base import VMNotFoundError


@pytest.fixture
def vmware_adapter():
    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = "session-token-12345"
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        adapter = VMwareAdapter(
            endpoint="https://vcenter.test",
            username="admin@vsphere.local",
            password="secretpassword",
            verify_ssl=False,
        )
        return adapter


def test_vmware_list_vms(vmware_adapter):
    mock_payload = [
        {
            "vm": "vm-100",
            "name": "enterprise-app-01",
            "power_state": "POWERED_ON",
            "cpu_count": 8,
            "memory_size_MiB": 16384,
        },
        {
            "vm": "vm-101",
            "name": "staging-db",
            "power_state": "POWERED_OFF",
            "cpu_count": 4,
            "memory_size_MiB": 8192,
        }
    ]
    with patch.object(vmware_adapter, "_request", return_value=mock_payload):
        vms = vmware_adapter.list_vms()
        assert len(vms) == 2
        assert vms[0].vm_id == "vm-100"
        assert vms[0].status == PowerState.RUNNING
        assert vms[0].cpu_cores == 8
        assert vms[0].memory_mb == 16384
        assert vms[1].status == PowerState.STOPPED


def test_vmware_start_vm(vmware_adapter):
    with patch.object(vmware_adapter, "_request", return_value={}):
        res = vmware_adapter.start_vm("vm-100")
        assert res.status == "completed"
        assert res.vm_id == "vm-100"


def test_vmware_stop_vm(vmware_adapter):
    with patch.object(vmware_adapter, "_request", return_value={}):
        res = vmware_adapter.stop_vm("vm-100", force=True)
        assert res.status == "completed"


def test_vmware_resize_vm(vmware_adapter):
    with patch.object(vmware_adapter, "_request", return_value={}):
        res = vmware_adapter.resize_vm("vm-100", VMResizeRequest(cpu_cores=16, memory_mb=32768))
        assert res.status == "completed"
