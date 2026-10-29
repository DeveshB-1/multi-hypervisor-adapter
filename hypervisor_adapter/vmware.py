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


class VMwareAdapter(BaseComputeAdapter):
    """
    Adapter for VMware vSphere vCenter REST API (vSphere 7.0 / 8.0).
    Manages session tokens automatically and handles power, hardware, and lifecycle operations.
    """

    def __init__(
        self,
        endpoint: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: int = 30,
    ) -> None:
        super().__init__(endpoint=endpoint, verify_ssl=verify_ssl, timeout=timeout)
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._session_token: Optional[str] = None

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False

        self._login()

    @property
    def hypervisor_type(self) -> HypervisorType:
        return HypervisorType.VMWARE

    def _login(self) -> None:
        url = f"{self.endpoint}/api/session"
        try:
            resp = self.session.post(
                url,
                auth=(self.username, self.password),
                timeout=self.timeout,
            )
            if resp.status_code == 401:
                raise HypervisorAuthError(f"vCenter login failed for {self.username} at {self.endpoint}")
            resp.raise_for_status()
            # In vCenter REST API, /api/session returns a string token or JSON string
            token = resp.json()
            if isinstance(token, dict) and "value" in token:
                token = token["value"]
            self._session_token = str(token).strip('"')
            self.session.headers.update({
                "vmware-api-session-id": self._session_token,
                "Content-Type": "application/json",
            })
        except requests.exceptions.RequestException as e:
            raise HypervisorConnectionError(f"Failed to connect to vCenter at {self.endpoint}: {e}") from e

    def _request(self, method: str, path: str, retry_on_auth: bool = True, **kwargs) -> Any:
        url = f"{self.endpoint}{path}"
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 401 and retry_on_auth:
                logger.info("vCenter session token expired. Re-authenticating...")
                self._login()
                return self._request(method, path, retry_on_auth=False, **kwargs)

            if resp.status_code == 404:
                raise VMNotFoundError(f"vCenter resource not found: {path}")

            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise HypervisorError(f"vCenter API error ({resp.status_code}): {resp.text}") from e
        except requests.exceptions.RequestException as e:
            raise HypervisorConnectionError(f"vCenter connection error: {e}") from e

    def ping(self) -> bool:
        try:
            self._request("GET", "/api/vcenter/vm")
            return True
        except Exception:
            return False

    def _map_power_state(self, status: str) -> PowerState:
        s = (status or "").upper()
        if s == "POWERED_ON":
            return PowerState.RUNNING
        elif s == "POWERED_OFF":
            return PowerState.STOPPED
        elif s == "SUSPENDED":
            return PowerState.SUSPENDED
        return PowerState.UNKNOWN

    def list_vms(self) -> List[VMInfo]:
        data = self._request("GET", "/api/vcenter/vm")
        vms = data if isinstance(data, list) else data.get("value", [])

        results = []
        for vm in vms:
            vm_id = vm.get("vm")
            name = vm.get("name", vm_id)
            status = self._map_power_state(vm.get("power_state"))
            cores = int(vm.get("cpu_count", 1))
            mem_mb = int(vm.get("memory_size_MiB", 1024))

            results.append(
                VMInfo(
                    vm_id=vm_id,
                    name=name,
                    status=status,
                    hypervisor=HypervisorType.VMWARE,
                    cpu_cores=cores,
                    memory_mb=mem_mb,
                    raw_metadata=vm,
                )
            )
        return results

    def get_vm(self, vm_id: str) -> VMInfo:
        vm = self._request("GET", f"/api/vcenter/vm/{vm_id}")
        data = vm if isinstance(vm, dict) and "power_state" in vm else vm.get("value", {})
        if not data:
            raise VMNotFoundError(f"VM {vm_id} not found in vCenter")

        name = data.get("name", vm_id)
        status = self._map_power_state(data.get("power_state"))
        
        cpu_info = data.get("cpu", {})
        cores = int(cpu_info.get("count", 1)) if isinstance(cpu_info, dict) else 1

        mem_info = data.get("memory", {})
        mem_mb = int(mem_info.get("size_MiB", 1024)) if isinstance(mem_info, dict) else 1024

        # Extract disk capacities if present
        disks = data.get("disks", {})
        total_disk_gb = 0.0
        if isinstance(disks, dict):
            for d in disks.values():
                cap = d.get("capacity", 0)
                total_disk_gb += cap / (1024 * 1024 * 1024)

        return VMInfo(
            vm_id=vm_id,
            name=name,
            status=status,
            hypervisor=HypervisorType.VMWARE,
            cpu_cores=cores,
            memory_mb=mem_mb,
            disk_gb=round(total_disk_gb, 2) if total_disk_gb > 0 else None,
            raw_metadata=data,
        )

    def start_vm(self, vm_id: str) -> TaskResult:
        self._request("POST", f"/api/vcenter/vm/{vm_id}/power?action=start")
        return TaskResult(
            task_id="ok",
            status="completed",
            message=f"Power on command issued for vCenter VM {vm_id}",
            vm_id=vm_id,
        )

    def stop_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        if force:
            self._request("POST", f"/api/vcenter/vm/{vm_id}/power?action=stop")
            msg = f"Hard power-off issued for vCenter VM {vm_id}"
        else:
            try:
                self._request("POST", f"/api/vcenter/vm/{vm_id}/guest/power?action=shutdown")
                msg = f"Graceful guest shutdown issued for vCenter VM {vm_id}"
            except Exception:
                logger.info("Guest shutdown failed or unsupported tools; falling back to power stop.")
                self._request("POST", f"/api/vcenter/vm/{vm_id}/power?action=stop")
                msg = f"Power-off issued for vCenter VM {vm_id}"

        return TaskResult(
            task_id="ok",
            status="completed",
            message=msg,
            vm_id=vm_id,
        )

    def restart_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        if force:
            self._request("POST", f"/api/vcenter/vm/{vm_id}/power?action=reset")
            msg = f"Hard reset issued for vCenter VM {vm_id}"
        else:
            try:
                self._request("POST", f"/api/vcenter/vm/{vm_id}/guest/power?action=reboot")
                msg = f"Graceful guest reboot issued for vCenter VM {vm_id}"
            except Exception:
                self._request("POST", f"/api/vcenter/vm/{vm_id}/power?action=reset")
                msg = f"Reset issued for vCenter VM {vm_id}"

        return TaskResult(
            task_id="ok",
            status="completed",
            message=msg,
            vm_id=vm_id,
        )

    def create_vm(self, request: VMCreateRequest) -> TaskResult:
        """
        Deploy VM from a library template or clone specification.
        Uses /api/vcenter/vm-template/library-items/{item}?action=deploy if from content library.
        """
        template_id = request.template_id
        url = f"/api/vcenter/vm-template/library-items/{template_id}?action=deploy"
        payload: Dict[str, Any] = {
            "name": request.name,
        }
        if request.storage_pool:
            payload["placement"] = {"datastore": request.storage_pool}
        if request.target_node:
            payload.setdefault("placement", {})["host"] = request.target_node

        resp = self._request("POST", url, json=payload)
        new_vm_id = resp if isinstance(resp, str) else resp.get("value", "pending")

        # Update sizing if deployed
        if new_vm_id and new_vm_id != "pending":
            try:
                self.resize_vm(new_vm_id, VMResizeRequest(cpu_cores=request.cpu_cores, memory_mb=request.memory_mb))
            except Exception as e:
                logger.warning(f"Could not resize newly created vCenter VM {new_vm_id}: {e}")

        return TaskResult(
            task_id="deployed",
            status="completed",
            message=f"VM {new_vm_id} ({request.name}) deployed from vCenter template {template_id}",
            vm_id=str(new_vm_id),
        )

    def resize_vm(self, vm_id: str, request: VMResizeRequest) -> TaskResult:
        if request.cpu_cores is not None:
            self._request("PATCH", f"/api/vcenter/vm/{vm_id}/hardware/cpu", json={"count": request.cpu_cores})
        if request.memory_mb is not None:
            self._request("PATCH", f"/api/vcenter/vm/{vm_id}/hardware/memory", json={"size_MiB": request.memory_mb})

        return TaskResult(
            task_id="ok",
            status="completed",
            message=f"vCenter VM {vm_id} hardware updated",
            vm_id=vm_id,
        )

    def delete_vm(self, vm_id: str) -> TaskResult:
        self._request("DELETE", f"/api/vcenter/vm/{vm_id}")
        return TaskResult(
            task_id="ok",
            status="completed",
            message=f"vCenter VM {vm_id} deleted successfully",
            vm_id=vm_id,
        )
