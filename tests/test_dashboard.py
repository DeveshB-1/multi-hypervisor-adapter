from fastapi.testclient import TestClient
from unittest.mock import MagicMock
import pytest

from hypervisor_adapter import (
    HypervisorType,
    MultiHypervisorClient,
    PowerState,
    TaskResult,
    VMInfo,
)
from hypervisor_adapter.dashboard import create_dashboard_app


@pytest.fixture
def test_client():
    client = MultiHypervisorClient()

    mock_proxmox = MagicMock()
    mock_proxmox.hypervisor_type = HypervisorType.PROXMOX
    mock_proxmox.list_vms.return_value = [
        VMInfo(
            vm_id="100",
            name="demo-web",
            status=PowerState.RUNNING,
            hypervisor=HypervisorType.PROXMOX,
            cpu_cores=4,
            memory_mb=8192,
        )
    ]
    mock_proxmox.start_vm.return_value = TaskResult(task_id="t1", status="queued")
    mock_proxmox.stop_vm.return_value = TaskResult(task_id="t2", status="queued")
    mock_proxmox.resize_vm.return_value = TaskResult(task_id="t3", status="completed", message="Resized")

    client.register("zone-a", mock_proxmox)

    app = create_dashboard_app(client)
    return TestClient(app)


def test_dashboard_html_render(test_client):
    res = test_client.get("/")
    assert res.status_code == 200
    assert "Hypervisor Controller" in res.text
    assert "Multi-Hypervisor" in res.text


def test_dashboard_api_clusters(test_client):
    res = test_client.get("/api/v1/clusters")
    assert res.status_code == 200
    assert res.json() == {"clusters": ["zone-a"]}


def test_dashboard_api_vms(test_client):
    res = test_client.get("/api/v1/vms")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["vm_id"] == "100"
    assert data[0]["cluster"] == "zone-a"


def test_dashboard_api_actions(test_client):
    # Start
    res = test_client.post("/api/v1/vms/zone-a/100/start")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Stop
    res = test_client.post("/api/v1/vms/zone-a/100/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Resize
    res = test_client.post("/api/v1/vms/zone-a/100/resize", json={"cpu_cores": 8, "memory_mb": 16384})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
