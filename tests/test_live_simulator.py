import threading
import time
import pytest
import uvicorn

from hypervisor_adapter import (
    MultiHypervisorClient,
    PowerState,
    ProxmoxAdapter,
    VMCreateRequest,
    VMResizeRequest,
    VMwareAdapter,
)
from hypervisor_adapter.simulator import create_simulator_app

PORT = 8999
HOST = "127.0.0.1"
ENDPOINT = f"http://{HOST}:{PORT}"


@pytest.fixture(scope="module")
def live_server():
    app = create_simulator_app()
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.5)  # Wait for server to bind
    yield
    server.should_exit = True
    thread.join(timeout=2)


def test_live_proxmox_lifecycle(live_server):
    adapter = ProxmoxAdapter(
        endpoint=ENDPOINT,
        token_id="root@pam!token",
        token_secret="dummy",
        verify_ssl=False,
    )
    assert adapter.ping() is True

    # 1. List
    vms = adapter.list_vms()
    assert len(vms) >= 2
    vm_map = {v.vm_id: v for v in vms}
    assert "100" in vm_map
    assert vm_map["100"].name == "kvm-web-prod-01"

    # 2. Stop & Start
    adapter.stop_vm("100")
    vm = adapter.get_vm("100")
    assert vm.status == PowerState.STOPPED

    adapter.start_vm("100")
    vm = adapter.get_vm("100")
    assert vm.status == PowerState.RUNNING

    # 3. Resize
    adapter.resize_vm("100", VMResizeRequest(cpu_cores=8, memory_mb=16384))
    vm = adapter.get_vm("100")
    assert vm.cpu_cores == 8
    assert vm.memory_mb == 16384

    # 4. Clone template
    res = adapter.create_vm(
        VMCreateRequest(
            name="new-clone-web",
            template_id="9000",
            cpu_cores=4,
            memory_mb=8192,
        )
    )
    new_id = res.vm_id
    assert new_id is not None
    cloned_vm = adapter.get_vm(new_id)
    assert cloned_vm.name == "new-clone-web"


def test_live_vmware_lifecycle(live_server):
    adapter = VMwareAdapter(
        endpoint=ENDPOINT,
        username="administrator@vsphere.local",
        password="any",
        verify_ssl=False,
    )
    assert adapter.ping() is True

    # 1. List
    vms = adapter.list_vms()
    assert len(vms) >= 2
    vm_map = {v.vm_id: v for v in vms}
    assert "vm-1001" in vm_map
    assert vm_map["vm-1001"].status == PowerState.RUNNING

    # 2. Stop & Start
    adapter.stop_vm("vm-1001", force=True)
    vm = adapter.get_vm("vm-1001")
    assert vm.status == PowerState.STOPPED

    adapter.start_vm("vm-1001")
    vm = adapter.get_vm("vm-1001")
    assert vm.status == PowerState.RUNNING

    # 3. Resize
    adapter.resize_vm("vm-1001", VMResizeRequest(cpu_cores=12, memory_mb=24576))
    vm = adapter.get_vm("vm-1001")
    assert vm.cpu_cores == 12
    assert vm.memory_mb == 24576


def test_live_multi_cluster_aggregation(live_server):
    client = MultiHypervisorClient()
    client.register(
        "proxmox-local",
        ProxmoxAdapter(endpoint=ENDPOINT, token_id="t", token_secret="s", verify_ssl=False),
    )
    client.register(
        "vmware-local",
        VMwareAdapter(endpoint=ENDPOINT, username="u", password="p", verify_ssl=False),
    )

    all_vms = client.list_vms()
    assert len(all_vms) >= 4
    hypervisors = {v.hypervisor.value for v in all_vms}
    assert hypervisors == {"proxmox", "vmware"}
