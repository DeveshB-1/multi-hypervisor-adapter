from __future__ import annotations

import argparse
import copy
import itertools
from typing import Any, Dict, Optional
import urllib.parse
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

# Pre-seeded virtual machines for Proxmox and VMware simulation
INITIAL_PROXMOX_VMS = {
    "100": {
        "vmid": 100,
        "name": "kvm-web-prod-01",
        "status": "running",
        "type": "qemu",
        "node": "pve1",
        "maxcpu": 4,
        "maxmem": 8589934592,  # 8 GB
        "maxdisk": 107374182400,  # 100 GB
        "uptime": 124500,
        "cores": 4,
        "memory": 8192,
    },
    "101": {
        "vmid": 101,
        "name": "kvm-db-prod-01",
        "status": "running",
        "type": "qemu",
        "node": "pve1",
        "maxcpu": 8,
        "maxmem": 17179869184,  # 16 GB
        "maxdisk": 536870912000,  # 500 GB
        "uptime": 450000,
        "cores": 8,
        "memory": 16384,
    },
    "9000": {
        "vmid": 9000,
        "name": "tpl-ubuntu-2404-cloudinit",
        "status": "stopped",
        "type": "qemu",
        "node": "pve1",
        "maxcpu": 2,
        "maxmem": 4294967296,
        "maxdisk": 32212254720,
        "uptime": 0,
        "template": 1,
        "cores": 2,
        "memory": 4096,
    },
}

INITIAL_VMWARE_VMS = {
    "vm-1001": {
        "vm": "vm-1001",
        "name": "esxi-app-finance-01",
        "power_state": "POWERED_ON",
        "cpu_count": 8,
        "memory_size_MiB": 16384,
        "cpu": {"count": 8, "cores_per_socket": 2},
        "memory": {"size_MiB": 16384},
        "disks": {"2000": {"capacity": 214748364800}},  # 200 GB
    },
    "vm-1002": {
        "vm": "vm-1002",
        "name": "esxi-core-db-01",
        "power_state": "POWERED_OFF",
        "cpu_count": 16,
        "memory_size_MiB": 32768,
        "cpu": {"count": 16, "cores_per_socket": 4},
        "memory": {"size_MiB": 32768},
        "disks": {"2000": {"capacity": 1073741824000}},  # 1 TB
    },
}


def create_simulator_app() -> FastAPI:
    app = FastAPI(title="Hypervisor Simulator (Proxmox VE & VMware vCenter)")

    proxmox_db = copy.deepcopy(INITIAL_PROXMOX_VMS)
    vmware_db = copy.deepcopy(INITIAL_VMWARE_VMS)
    vmid_seq = itertools.count(200)
    task_seq = itertools.count(1001)

    # ==========================================
    # Proxmox VE REST Endpoints (/api2/json/...)
    # ==========================================

    @app.get("/api2/json/version")
    def pve_version():
        return {"data": {"version": "8.1.4", "release": "8.1", "repoid": "mock-pve"}}

    @app.get("/api2/json/cluster/resources")
    def pve_cluster_resources(type: Optional[str] = None):
        if type == "vm":
            return {"data": list(proxmox_db.values())}
        return {"data": list(proxmox_db.values())}

    @app.get("/api2/json/cluster/nextid")
    def pve_nextid():
        return {"data": str(next(vmid_seq))}

    @app.get("/api2/json/nodes/{node}/qemu/{vmid}/status/current")
    def pve_vm_status(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        return {"data": vm}

    @app.get("/api2/json/nodes/{node}/qemu/{vmid}/config")
    def pve_vm_config(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        return {"data": {"cores": vm.get("cores", 2), "memory": vm.get("memory", 4096), "name": vm["name"]}}

    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/start")
    def pve_vm_start(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        vm["status"] = "running"
        return {"data": f"UPID:{node}:task_{next(task_seq)}:start"}

    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/stop")
    def pve_vm_stop(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        vm["status"] = "stopped"
        return {"data": f"UPID:{node}:task_{next(task_seq)}:stop"}

    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/shutdown")
    def pve_vm_shutdown(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        vm["status"] = "stopped"
        return {"data": f"UPID:{node}:task_{next(task_seq)}:shutdown"}

    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/reset")
    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/status/reboot")
    def pve_vm_reboot(node: str, vmid: str):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        vm["status"] = "running"
        return {"data": f"UPID:{node}:task_{next(task_seq)}:reboot"}

    @app.put("/api2/json/nodes/{node}/qemu/{vmid}/config")
    async def pve_vm_update_config(node: str, vmid: str, request: Request):
        vm = proxmox_db.get(str(vmid))
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Parse form data without multipart dependency
        body_bytes = await request.body()
        form = urllib.parse.parse_qs(body_bytes.decode(errors="replace"))
        if "cores" in form:
            cores = int(form["cores"][0])
            vm["cores"] = cores
            vm["maxcpu"] = cores
        if "memory" in form:
            mem = int(form["memory"][0])
            vm["memory"] = mem
            vm["maxmem"] = mem * 1024 * 1024
        return {"data": None}

    @app.post("/api2/json/nodes/{node}/qemu/{vmid}/clone")
    async def pve_vm_clone(node: str, vmid: str, request: Request):
        body_bytes = await request.body()
        form = urllib.parse.parse_qs(body_bytes.decode(errors="replace"))
        template = proxmox_db.get(str(vmid))
        if not template:
            raise HTTPException(status_code=404, detail="Template VM not found")

        newid_list = form.get("newid", [str(next(vmid_seq))])
        newid = str(newid_list[0])
        name_list = form.get("name", [f"clone-{newid}"])
        name = str(name_list[0])

        new_vm = copy.deepcopy(template)
        new_vm["vmid"] = int(newid)
        new_vm["name"] = name
        new_vm["status"] = "stopped"
        new_vm.pop("template", None)
        proxmox_db[newid] = new_vm

        return {"data": f"UPID:{node}:clone_{newid}:clone"}

    @app.delete("/api2/json/nodes/{node}/qemu/{vmid}")
    def pve_vm_delete(node: str, vmid: str):
        if str(vmid) not in proxmox_db:
            raise HTTPException(status_code=404, detail="VM not found")
        del proxmox_db[str(vmid)]
        return {"data": f"UPID:pve1:del_{vmid}:delete"}

    # ==========================================
    # VMware vCenter REST Endpoints (/api/...)
    # ==========================================

    @app.post("/api/session")
    def vmware_session():
        return "mock-session-token-9999"

    @app.get("/api/vcenter/vm")
    def vmware_list_vms():
        summary_list = []
        for vm in vmware_db.values():
            summary_list.append({
                "vm": vm["vm"],
                "name": vm["name"],
                "power_state": vm["power_state"],
                "cpu_count": vm["cpu_count"],
                "memory_size_MiB": vm["memory_size_MiB"],
            })
        return summary_list

    @app.get("/api/vcenter/vm/{vm_id}")
    def vmware_get_vm(vm_id: str):
        vm = vmware_db.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        return vm

    @app.post("/api/vcenter/vm/{vm_id}/power")
    def vmware_power(vm_id: str, action: str):
        vm = vmware_db.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        if action == "start":
            vm["power_state"] = "POWERED_ON"
        elif action in ("stop", "shutdown"):
            vm["power_state"] = "POWERED_OFF"
        elif action in ("reset", "reboot"):
            vm["power_state"] = "POWERED_ON"
        return {}

    @app.patch("/api/vcenter/vm/{vm_id}/hardware/cpu")
    async def vmware_patch_cpu(vm_id: str, request: Request):
        vm = vmware_db.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        data = await request.json()
        if "count" in data:
            vm["cpu_count"] = data["count"]
            vm["cpu"]["count"] = data["count"]
        return Response(status_code=204)

    @app.patch("/api/vcenter/vm/{vm_id}/hardware/memory")
    async def vmware_patch_memory(vm_id: str, request: Request):
        vm = vmware_db.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="VM not found")
        data = await request.json()
        if "size_MiB" in data:
            vm["memory_size_MiB"] = data["size_MiB"]
            vm["memory"]["size_MiB"] = data["size_MiB"]
        return Response(status_code=204)

    @app.delete("/api/vcenter/vm/{vm_id}")
    def vmware_delete_vm(vm_id: str):
        if vm_id not in vmware_db:
            raise HTTPException(status_code=404, detail="VM not found")
        del vmware_db[vm_id]
        return Response(status_code=204)

    return app


def main():
    parser = argparse.ArgumentParser(description="Run Hypervisor Mock Server")
    parser.add_argument("--port", type=int, default=8006, help="Port to bind (default: 8006)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"Starting Hypervisor Simulator on http://{args.host}:{args.port}")
    print(f"  Proxmox VE Endpoint : http://{args.host}:{args.port}")
    print(f"  VMware vCenter URL  : http://{args.host}:{args.port}")
    app = create_simulator_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
