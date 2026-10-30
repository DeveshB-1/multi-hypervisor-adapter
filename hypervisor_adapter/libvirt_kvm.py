from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

from hypervisor_adapter.base import (
    BaseComputeAdapter,
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

try:
    import libvirt
except ImportError:
    libvirt = None


class LibvirtKvmAdapter(BaseComputeAdapter):
    """
    Adapter for local/remote KVM hypervisors via Libvirt (qemu:///session or qemu:///system).
    Directly drives /dev/kvm with hardware virtualization on Linux bare metal.
    """

    def __init__(
        self,
        uri: str = "qemu:///session",
        storage_dir: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        super().__init__(endpoint=uri, verify_ssl=False, timeout=timeout)
        if libvirt is None:
            raise HypervisorError(
                "libvirt-python is required to use LibvirtKvmAdapter. Install it with: pip install libvirt-python"
            )
        self.uri = uri
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path.home() / ".local" / "share" / "multi-hypervisor-adapter" / "disks"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def hypervisor_type(self) -> HypervisorType:
        return HypervisorType.KVM

    def _get_connection(self):
        try:
            conn = libvirt.open(self.uri)
            if conn is None:
                raise HypervisorConnectionError(f"Failed to open connection to libvirt URI: {self.uri}")
            return conn
        except libvirt.libvirtError as e:
            raise HypervisorConnectionError(f"Libvirt connection error ({self.uri}): {e}") from e

    def ping(self) -> bool:
        try:
            conn = self._get_connection()
            alive = conn.isAlive() == 1
            conn.close()
            return alive
        except Exception:
            return False

    def _map_libvirt_state(self, state_code: int) -> PowerState:
        # libvirt.VIR_DOMAIN_RUNNING = 1, BLOCKED = 2, PAUSED = 3, SHUTDOWN = 4, SHUTOFF = 5, CRASHED = 6, PMSUSPENDED = 7
        if state_code == 1:
            return PowerState.RUNNING
        elif state_code in (3, 7):
            return PowerState.SUSPENDED
        elif state_code in (4, 5):
            return PowerState.STOPPED
        return PowerState.UNKNOWN

    def list_vms(self) -> List[VMInfo]:
        conn = self._get_connection()
        try:
            domains = conn.listAllDomains(0)
            results = []
            for dom in domains:
                try:
                    name = dom.name()
                    uuid = dom.UUIDString()
                    state_info = dom.state()
                    status = self._map_libvirt_state(state_info[0])

                    # Parse XML for CPU & Memory
                    xml_desc = dom.XMLDesc(0)
                    root = ET.fromstring(xml_desc)
                    vcpu_elem = root.find("vcpu")
                    cores = int(vcpu_elem.text) if vcpu_elem is not None and vcpu_elem.text else 1

                    mem_elem = root.find("memory")
                    mem_unit = mem_elem.get("unit", "KiB") if mem_elem is not None else "KiB"
                    mem_val = int(mem_elem.text) if mem_elem is not None and mem_elem.text else 1048576
                    if mem_unit == "KiB":
                        mem_mb = mem_val // 1024
                    elif mem_unit == "bytes":
                        mem_mb = mem_val // (1024 * 1024)
                    else:
                        mem_mb = mem_val

                    results.append(
                        VMInfo(
                            vm_id=uuid,
                            name=name,
                            status=status,
                            hypervisor=HypervisorType.KVM,
                            cpu_cores=cores,
                            memory_mb=mem_mb,
                            node="localhost",
                            raw_metadata={"uuid": uuid, "name": name, "state": state_info[0]},
                        )
                    )
                except Exception as e:
                    logger.warning(f"Error inspecting libvirt domain: {e}")
            return results
        finally:
            conn.close()

    def _find_domain(self, conn, vm_id: str):
        try:
            # Try by UUID
            return conn.lookupByUUIDString(vm_id)
        except libvirt.libvirtError:
            pass

        try:
            # Try by Name
            return conn.lookupByName(vm_id)
        except libvirt.libvirtError:
            raise VMNotFoundError(f"KVM virtual machine '{vm_id}' not found in {self.uri}")

    def get_vm(self, vm_id: str) -> VMInfo:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            name = dom.name()
            uuid = dom.UUIDString()
            state_info = dom.state()
            status = self._map_libvirt_state(state_info[0])

            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            vcpu_elem = root.find("vcpu")
            cores = int(vcpu_elem.text) if vcpu_elem is not None and vcpu_elem.text else 1

            mem_elem = root.find("memory")
            mem_unit = mem_elem.get("unit", "KiB") if mem_elem is not None else "KiB"
            mem_val = int(mem_elem.text) if mem_elem is not None and mem_elem.text else 1048576
            mem_mb = mem_val // 1024 if mem_unit == "KiB" else mem_val

            return VMInfo(
                vm_id=uuid,
                name=name,
                status=status,
                hypervisor=HypervisorType.KVM,
                cpu_cores=cores,
                memory_mb=mem_mb,
                node="localhost",
                raw_metadata={"uuid": uuid, "name": name, "state": state_info[0]},
            )
        finally:
            conn.close()

    def start_vm(self, vm_id: str) -> TaskResult:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            if dom.isActive() == 1:
                return TaskResult(task_id="noop", status="completed", message=f"VM {vm_id} is already running", vm_id=vm_id)
            dom.create()
            return TaskResult(task_id=f"start_{dom.ID()}", status="completed", message=f"VM '{dom.name()}' booted on /dev/kvm", vm_id=dom.UUIDString())
        except libvirt.libvirtError as e:
            raise HypervisorError(f"Failed to start VM {vm_id}: {e}") from e
        finally:
            conn.close()

    def stop_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            if dom.isActive() == 0:
                return TaskResult(task_id="noop", status="completed", message=f"VM {vm_id} is already stopped", vm_id=vm_id)
            if force:
                dom.destroy()
                msg = f"VM '{dom.name()}' destroyed (hard power off)"
            else:
                try:
                    dom.shutdown()
                    msg = f"VM '{dom.name()}' ACPI shutdown signaled"
                except Exception:
                    dom.destroy()
                    msg = f"VM '{dom.name()}' destroyed (fallback to hard stop)"
            return TaskResult(task_id="stop_ok", status="completed", message=msg, vm_id=dom.UUIDString())
        except libvirt.libvirtError as e:
            raise HypervisorError(f"Failed to stop VM {vm_id}: {e}") from e
        finally:
            conn.close()

    def restart_vm(self, vm_id: str, force: bool = False) -> TaskResult:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            if force or dom.isActive() == 0:
                if dom.isActive() == 1:
                    dom.destroy()
                dom.create()
                msg = f"VM '{dom.name()}' hard reset completed"
            else:
                dom.reboot(0)
                msg = f"VM '{dom.name()}' reboot command issued"
            return TaskResult(task_id="reboot_ok", status="completed", message=msg, vm_id=dom.UUIDString())
        except libvirt.libvirtError as e:
            raise HypervisorError(f"Failed to reboot VM {vm_id}: {e}") from e
        finally:
            conn.close()

    def resize_vm(self, vm_id: str, request: VMResizeRequest) -> TaskResult:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            # Update memory
            if request.memory_mb is not None:
                mem_kib = request.memory_mb * 1024
                try:
                    # Update active live memory if running
                    if dom.isActive() == 1:
                        dom.setMemory(mem_kib)
                except Exception as e:
                    logger.warning(f"Could not live-update RAM: {e}")
                # Update persistent config XML
                try:
                    dom.setMemoryFlags(mem_kib, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
                except Exception:
                    pass

            # Update vCPU
            if request.cpu_cores is not None:
                try:
                    dom.setVcpusFlags(request.cpu_cores, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
                    if dom.isActive() == 1:
                        dom.setVcpus(request.cpu_cores)
                except Exception as e:
                    logger.warning(f"Could not update vCPU: {e}")

            return TaskResult(task_id="resize_ok", status="completed", message=f"VM '{dom.name()}' resources updated", vm_id=dom.UUIDString())
        except libvirt.libvirtError as e:
            raise HypervisorError(f"Failed to resize VM {vm_id}: {e}") from e
        finally:
            conn.close()

    def create_vm(self, request: VMCreateRequest) -> TaskResult:
        """
        Provisions a real hardware-accelerated KVM virtual machine.
        If template_id is an existing qcow2/raw path, creates a fast copy-on-write overlay.
        """
        conn = self._get_connection()
        try:
            vm_name = request.name.replace(" ", "-")
            disk_path = self.storage_dir / f"{vm_name}.qcow2"

            disk_xml = ""
            template_path = Path(request.template_id)
            if template_path.is_file():
                # Fast Copy-on-Write overlay based on template
                cmd = ["qemu-img", "create", "-f", "qcow2", "-b", str(template_path.resolve()), "-F", "qcow2", str(disk_path)]
                subprocess.run(cmd, check=True, capture_output=True)
            elif not disk_path.exists():
                # Blank virtual disk
                disk_size_gb = request.disk_gb or 10
                cmd = ["qemu-img", "create", "-f", "qcow2", str(disk_path), f"{disk_size_gb}G"]
                subprocess.run(cmd, check=True, capture_output=True)

            disk_xml = f"""
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{disk_path.resolve()}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            """

            memory_kib = request.memory_mb * 1024
            xml = f"""
            <domain type='kvm'>
              <name>{vm_name}</name>
              <memory unit='KiB'>{memory_kib}</memory>
              <currentMemory unit='KiB'>{memory_kib}</currentMemory>
              <vcpu placement='static'>{request.cpu_cores}</vcpu>
              <os>
                <type arch='x86_64' machine='q35'>hvm</type>
                <boot dev='hd'/>
              </os>
              <features>
                <acpi/>
                <apic/>
              </features>
              <cpu mode='host-passthrough' check='none'/>
              <devices>
                <emulator>/usr/bin/qemu-system-x86_64</emulator>
                {disk_xml}
                <interface type='user'>
                  <model type='virtio'/>
                </interface>
                <console type='pty'>
                  <target type='serial' port='0'/>
                </console>
                <memballoon model='virtio'/>
              </devices>
            </domain>
            """
            dom = conn.defineXML(xml)
            dom_uuid = dom.UUIDString()
            return TaskResult(
                task_id=f"create_{dom_uuid}",
                status="completed",
                message=f"Real KVM instance '{vm_name}' defined with {request.cpu_cores} vCPU and {request.memory_mb}MB RAM",
                vm_id=dom_uuid,
            )
        except Exception as e:
            raise HypervisorError(f"Failed to create KVM VM '{request.name}': {e}") from e
        finally:
            conn.close()

    def delete_vm(self, vm_id: str) -> TaskResult:
        conn = self._get_connection()
        try:
            dom = self._find_domain(conn, vm_id)
            name = dom.name()
            uuid = dom.UUIDString()
            if dom.isActive() == 1:
                dom.destroy()
            dom.undefine()

            # Clean disk if found in storage dir
            disk_path = self.storage_dir / f"{name}.qcow2"
            if disk_path.exists():
                try:
                    disk_path.unlink()
                except Exception:
                    pass

            return TaskResult(task_id="delete_ok", status="completed", message=f"KVM instance '{name}' deleted", vm_id=uuid)
        except libvirt.libvirtError as e:
            raise HypervisorError(f"Failed to delete VM {vm_id}: {e}") from e
        finally:
            conn.close()
