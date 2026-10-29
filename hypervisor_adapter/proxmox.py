from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import requests
import urllib3

from hypervisor_adapter.base import (
    BaseComputeAdapter,
    HypervisorAuthError,
    HypervisorConnectionError,
    HypervisorError,
    VMNotFoundError,
)
from hypervisor_adapter.models import (
    HypervisorType,
    PowerState,
    TaskResult,
    VMCreateRequest,
    VMInfo,
    VMResizeRequest,
)

logger = logging.getLogger(__name__)


class ProxmoxAdapter(BaseComputeAdapter):
    """
    Adapter for Proxmox VE (KVM/QEMU).
    Supports token authentication (recommended for API/microservices) and ticket authentication.
    """

    def __init__(
        self,
        endpoint: str,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        default_node: str = "pve",
        verify_ssl: bool = False,
        timeout: int = 30,
    ) -> None:
        super().__init__(endpoint=endpoint, verify_ssl=verify_ssl, timeout=timeout)
        self.token_id = token_id
        self.token_secret = token_secret
        self.username = username
        self.password = password
        self.default_node = default_node
        self.session = requests.Session()

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False

        self._ticket: Optional[str] = None
        self._csrf_token: Optional[str] = None
        self._init_auth()

    @property
    def hypervisor_type(self) -> HypervisorType:
        return HypervisorType.PROXMOX

    def _init_auth(self) -> None:
        if self.token_id and self.token_secret:
            # Token header format: PVEAPIToken=USER@REALM!TOKENID=UUID
            self.session.headers.update({
                "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}",
            })
        elif self.username and self.password:
            self._login_ticket()
        else:
            raise HypervisorAuthError("Either (token_id, token_secret) or (username, password) must be provided.")

    def _login_ticket(self) -> None:
        url = f"{self.endpoint}/api2/json/access/ticket"
        try:
            resp = self.session.post(
                url,
                data={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
            if resp.status_code == 401:
                raise HypervisorAuthError("Proxmox authentication failed: invalid username or password")
            resp.raise_for_status()
            data = resp.json().get("data", {})
            self._ticket = data.get("ticket")
            self._csrf_token = data.get("CSRFPreventionToken")
            self.session.cookies.set("PVEAuthCookie", self._ticket)
            if self._csrf_token:
                self.session.headers.update({"CSRFPreventionToken": self._csrf_token})
        except requests.exceptions.RequestException as e:
            raise HypervisorConnectionError(f"Failed to connect to Proxmox at {self.endpoint}: {e}") from e

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.endpoint}/api2/json{path}"
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 401:
                raise HypervisorAuthError("Proxmox API returned 401 Unauthorized.")
            if resp.status_code == 404:
                raise VMNotFoundError(f"Resource not found at {path}")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise HypervisorError(f"Proxmox API error ({resp.status_code}): {resp.text}") from e
        except requests.exceptions.RequestException as e:
            raise HypervisorConnectionError(f"Proxmox connection error: {e}") from e

    def ping(self) -> bool:
        try:
            data = self._request("GET", "/version")
            return "version" in data.get("data", {})
        except Exception:
            return False

    def _find_node_for_vmid(self, vmid: str) -> str:
        data = self._request("GET", "/cluster/resources?type=vm")
        for item in data.get("data", []):
            if str(item.get("vmid")) == str(vmid):
                return item.get("node", self.default_node)
        return self.default_node

    def _map_power_state(self, status: str) -> PowerState:
        s = (status or "").lower()
        if s == "running":
            return PowerState.RUNNING
        elif s == "stopped":
            return PowerState.STOPPED
        elif s in ("paused", "suspended"):
            return PowerState.SUSPENDED
        return PowerState.UNKNOWN

    def list_vms(self) -> List[VMInfo]:
        data = self._request("GET", "/cluster/resources?type=vm")
        results = []
        for vm in data.get("data", []):
            # Skip LXC containers if strictly looking for QEMU/KVM
            if vm.get("type") not in ("qemu", "vm"):
                continue
            
            vmid = str(vm.get("vmid"))
            name = vm.get("name", f"vm-{vmid}")
            status = self._map_power_state(vm.get("status"))
            cores = int(vm.get("maxcpu", 1))
            mem_mb = int(vm.get("maxmem", 0) / (1024 * 1024))
            disk_gb = round(vm.get("maxdisk", 0) / (1024 * 1024 * 1024), 2)
            node = vm.get("node", self.default_node)
            uptime = int(vm.get("uptime", 0))

            results.append(
                VMInfo(
                    vm_id=vmid,
                    name=name,
                    status=status,
                    hypervisor=HypervisorType.PROXMOX,
                    cpu_cores=cores,
                    memory_mb=mem_mb,
                    disk_gb=disk_gb,
                    node=node,
                    uptime_seconds=uptime,
                    raw_metadata=vm,
                )
            )
        return results

    def get_vm(self, vm_id: str) -> VMInfo:
        node = self._find_node_for_vmid(vm_id)
        status_resp = self._request("GET", f"/nodes/{node}/qemu/{vm_id}/status/current")
        data = status_resp.get("data", {})
        if not data:
            raise VMNotFoundError(f"VM {vm_id} not found on node {node}")

        config_resp = self._request("GET", f"/nodes/{node}/qemu/{vm_id}/config")
        config = config_resp.get("data", {})

        cores = int(config.get("cores", data.get("cpus", 1)))
        mem_mb = int(config.get("memory", data.get("maxmem", 0) // (1024 * 1024)))
        disk_gb = round(data.get("maxdisk", 0) / (1024 * 1024 * 1024), 2)

        return VMInfo(
            vm_id=str(vm_id),
            name=data.get("name", config.get("name", f"vm-{vm_id}")),
            status=self._map_power_state(data.get("status")),
            hypervisor=HypervisorType.PROXMOX,
            cpu_cores=cores,
            memory_mb=mem_mb,
            disk_gb=disk_gb,
            node=node,
            uptime_seconds=int(data.get("uptime", 0)),
            raw_metadata={"status": data, "config": config},
        )

    def start_vm(self, vm_id: str) -> TaskResult:
        node = self._find_node_for_vmid(vm_id)
        resp = self._request("POST", f"/nodes/{node}/qemu/{vm_id}/status/start")
        return TaskResult(
            task_id=resp.get("data", "ok"),
            status="queued",
            message=f"Start command issued for VM {vm_id}",
            vm_id=vm_id,
        )

    def stop_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        node = self._find_node_for_vmid(vm_id)
        action = "stop" if force else "shutdown"
        resp = self._request("POST", f"/nodes/{node}/qemu/{vm_id}/status/{action}")
        return TaskResult(
            task_id=resp.get("data", "ok"),
            status="queued",
            message=f"{action.capitalize()} command issued for VM {vm_id}",
            vm_id=vm_id,
        )

    def restart_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        node = self._find_node_for_vmid(vm_id)
        action = "reset" if force else "reboot"
        resp = self._request("POST", f"/nodes/{node}/qemu/{vm_id}/status/{action}")
        return TaskResult(
            task_id=resp.get("data", "ok"),
            status="queued",
            message=f"{action.capitalize()} command issued for VM {vm_id}",
            vm_id=vm_id,
        )

    def create_vm(self, request: VMCreateRequest) -> TaskResult:
        node = request.target_node or self.default_node
        template_id = request.template_id

        # Allocate new VM ID if not specified
        nextid_resp = self._request("GET", "/cluster/nextid")
        new_vmid = str(nextid_resp.get("data"))

        clone_payload: Dict[str, Any] = {
            "newid": new_vmid,
            "name": request.name,
            "full": 1,
        }
        if request.storage_pool:
            clone_payload["storage"] = request.storage_pool

        clone_resp = self._request("POST", f"/nodes/{node}/qemu/{template_id}/clone", data=clone_payload)
        task_id = clone_resp.get("data", "ok")

        # Configure hardware & cloud-init parameters
        config_payload: Dict[str, Any] = {
            "cores": request.cpu_cores,
            "memory": request.memory_mb,
        }
        if request.cloud_init_user:
            config_payload["ciuser"] = request.cloud_init_user
        if request.cloud_init_password:
            config_payload["cipassword"] = request.cloud_init_password
        if request.cloud_init_ssh_key:
            config_payload["sshkeys"] = request.cloud_init_ssh_key
        if request.ip_cidr:
            gw_clause = f",gw={request.gateway}" if request.gateway else ""
            config_payload["ipconfig0"] = f"ip={request.ip_cidr}{gw_clause}"

        try:
            self._request("PUT", f"/nodes/{node}/qemu/{new_vmid}/config", data=config_payload)
        except Exception as e:
            logger.warning(f"Config update pending or failed for VM {new_vmid}: {e}")

        return TaskResult(
            task_id=task_id,
            status="queued",
            message=f"VM {new_vmid} ({request.name}) clone initiated from template {template_id}",
            vm_id=new_vmid,
        )

    def resize_vm(self, vm_id: str, request: VMResizeRequest) -> TaskResult:
        node = self._find_node_for_vmid(vm_id)
        payload: Dict[str, Any] = {}
        if request.cpu_cores is not None:
            payload["cores"] = request.cpu_cores
        if request.memory_mb is not None:
            payload["memory"] = request.memory_mb

        if not payload:
            return TaskResult(task_id="noop", status="completed", message="No parameters to resize", vm_id=vm_id)

        self._request("PUT", f"/nodes/{node}/qemu/{vm_id}/config", data=payload)
        return TaskResult(
            task_id="ok",
            status="completed",
            message=f"VM {vm_id} hardware configuration updated",
            vm_id=vm_id,
        )

    def delete_vm(self, vm_id: str) -> TaskResult:
        node = self._find_node_for_vmid(vm_id)
        resp = self._request("DELETE", f"/nodes/{node}/qemu/{vm_id}?purge=1&destroy-unreferenced-disks=1")
        return TaskResult(
            task_id=resp.get("data", "ok"),
            status="queued",
            message=f"VM {vm_id} deletion initiated",
            vm_id=vm_id,
        )
