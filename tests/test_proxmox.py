from unittest.mock import MagicMock, patch
import pytest

from hypervisor_adapter import ProxmoxAdapter, PowerState, VMCreateRequest, VMResizeRequest
from hypervisor_adapter.base import VMNotFoundError


@pytest.fixture
def proxmox_adapter():
    with patch("requests.Session"):
        adapter = ProxmoxAdapter(
            endpoint="https://proxmox.test:8006",
            token_id="root@pam!token",
            token_secret="mock-secret",
            verify_ssl=False,
        )
        return adapter


def test_proxmox_ping(proxmox_adapter):
    with patch.object(proxmox_adapter, "_request") as mock_req:
        mock_req.return_value = {"data": {"version": "8.1.3", "release": "8.1"}}
        assert proxmox_adapter.ping() is True


def test_proxmox_list_vms(proxmox_adapter):
    mock_payload = {
        "data": [
            {
                "vmid": 100,
                "name": "db-server",
                "status": "running",
                "type": "qemu",
                "maxcpu": 4,
                "maxmem": 8589934592,  # 8GB
                "maxdisk": 107374182400,  # 100GB
                "node": "pve1",
            },
            {
                "vmid": 101,
                "name": "web-server",
                "status": "stopped",
                "type": "qemu",
                "maxcpu": 2,
                "maxmem": 4294967296,
                "maxdisk": 53687091200,
                "node": "pve1",
            },
            {
                "vmid": 102,
                "name": "container-app",
                "status": "running",
                "type": "lxc",  # LXC container, should be skipped
            }
        ]
    }
    with patch.object(proxmox_adapter, "_request") as mock_req:
        mock_req.return_value = mock_payload
        vms = proxmox_adapter.list_vms()
        assert len(vms) == 2
        assert vms[0].vm_id == "100"
        assert vms[0].name == "db-server"
        assert vms[0].status == PowerState.RUNNING
        assert vms[0].cpu_cores == 4
        assert vms[0].memory_mb == 8192
        assert vms[1].status == PowerState.STOPPED


def test_proxmox_start_vm(proxmox_adapter):
    with patch.object(proxmox_adapter, "_find_node_for_vmid", return_value="pve1"), \
         patch.object(proxmox_adapter, "_request", return_value={"data": "UPID:pve1:0001:start"}):
        res = proxmox_adapter.start_vm("100")
        assert res.task_id == "UPID:pve1:0001:start"
        assert res.status == "queued"
        assert res.vm_id == "100"


def test_proxmox_stop_vm(proxmox_adapter):
    with patch.object(proxmox_adapter, "_find_node_for_vmid", return_value="pve1"), \
         patch.object(proxmox_adapter, "_request", return_value={"data": "UPID:pve1:0002:shutdown"}):
        res = proxmox_adapter.stop_vm("100", force=False)
        assert res.status == "queued"


def test_proxmox_resize_vm(proxmox_adapter):
    with patch.object(proxmox_adapter, "_find_node_for_vmid", return_value="pve1"), \
         patch.object(proxmox_adapter, "_request", return_value={"data": "ok"}):
        res = proxmox_adapter.resize_vm("100", VMResizeRequest(cpu_cores=8, memory_mb=16384))
        assert res.status == "completed"
