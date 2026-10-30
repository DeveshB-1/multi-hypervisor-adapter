from __future__ import annotations

import argparse
import os
import threading
import time
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from hypervisor_adapter import (
    HypervisorType,
    LibvirtKvmAdapter,
    MultiHypervisorClient,
    PowerState,
    ProxmoxAdapter,
    VMCreateRequest,
    VMResizeRequest,
    VMwareAdapter,
)
from hypervisor_adapter.simulator import create_simulator_app

# Embedded single-page web console with Tailwind CSS
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Multi-Hypervisor Console</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' },
            dark: { 800: '#1e293b', 900: '#0f172a', 950: '#020617' }
          }
        }
      }
    }
  </script>
  <style>
    @keyframes pulse-subtle { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
    .status-running { animation: pulse-subtle 2s infinite ease-in-out; }
  </style>
</head>
<body class="bg-dark-950 text-slate-100 min-h-screen font-sans antialiased flex flex-col">
  <!-- Top Navigation -->
  <header class="border-b border-slate-800 bg-dark-900/80 backdrop-blur sticky top-0 z-30 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
        ⚡
      </div>
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
          Hypervisor Controller
          <span class="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">Unified CMP</span>
        </h1>
        <p class="text-xs text-slate-400">Proxmox KVM & VMware vSphere Unified Controller</p>
      </div>
    </div>
    <div class="flex items-center space-x-3">
      <button onclick="fetchInventory()" class="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition flex items-center gap-1.5">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
        Refresh
      </button>
      <button onclick="openDeployModal()" class="px-3 py-1.5 text-xs font-semibold rounded-md bg-blue-600 hover:bg-blue-500 text-white shadow-sm shadow-blue-500/30 transition flex items-center gap-1.5">
        + Deploy VM
      </button>
    </div>
  </header>

  <!-- Main Container -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-8 space-y-6">
    <!-- Cluster Cards Overview -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-5" id="stats-cards">
      <div class="bg-dark-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Active Clusters</div>
        <div class="mt-2 flex items-baseline justify-between">
          <div class="text-2xl font-bold text-white" id="stat-clusters">2</div>
          <span class="text-xs text-emerald-400 flex items-center gap-1">● Online</span>
        </div>
        <div class="mt-2 text-xs text-slate-500 flex gap-2">
          <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">Proxmox KVM</span>
          <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">vSphere 8.x</span>
        </div>
      </div>
      <div class="bg-dark-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Total Workloads</div>
        <div class="mt-2 flex items-baseline justify-between">
          <div class="text-2xl font-bold text-white" id="stat-total-vms">-</div>
          <div class="text-xs text-slate-400"><span id="stat-running-vms" class="text-emerald-400 font-semibold">0</span> Running</div>
        </div>
        <div class="mt-2 text-xs text-slate-500">Live compute across all zones</div>
      </div>
      <div class="bg-dark-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Allocated vCPU / RAM</div>
        <div class="mt-2 flex items-baseline justify-between">
          <div class="text-2xl font-bold text-white" id="stat-resources">-</div>
          <span class="text-xs text-blue-400">Dynamic Hotplug</span>
        </div>
        <div class="mt-2 text-xs text-slate-500">Zero-downtime scaling supported</div>
      </div>
    </div>

    <!-- VM Inventory Table -->
    <div class="bg-dark-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
        <div>
          <h2 class="text-base font-semibold text-white">Compute Instances</h2>
          <p class="text-xs text-slate-400 mt-0.5">Aggregated virtual machines across KVM and VMware</p>
        </div>
        <div id="loading-spinner" class="hidden text-xs text-blue-400 flex items-center gap-2">
          <svg class="animate-spin h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
          Syncing...
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="text-xs uppercase bg-slate-900/60 text-slate-400 border-b border-slate-800">
            <tr>
              <th class="px-6 py-3.5">Instance</th>
              <th class="px-6 py-3.5">Hypervisor</th>
              <th class="px-6 py-3.5">Cluster</th>
              <th class="px-6 py-3.5">Status</th>
              <th class="px-6 py-3.5">vCPU</th>
              <th class="px-6 py-3.5">Memory</th>
              <th class="px-6 py-3.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody id="vm-table-body" class="divide-y divide-slate-800">
            <!-- Rows injected by JavaScript -->
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <!-- Resize Modal -->
  <div id="resize-modal" class="hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-dark-900 border border-slate-700 rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
      <h3 class="text-lg font-bold text-white flex items-center gap-2">
        <span>⚡</span> Hotplug Resize VM
      </h3>
      <p class="text-xs text-slate-400">Scale CPU and RAM dynamically without rebooting the guest workload.</p>
      
      <input type="hidden" id="resize-cluster">
      <input type="hidden" id="resize-vmid">

      <div class="space-y-3 pt-2">
        <div>
          <label class="text-xs font-semibold text-slate-300 block mb-1">Target vCPUs (<span id="cpu-val">4</span> cores)</label>
          <input type="range" id="resize-cpu" min="1" max="32" value="4" oninput="document.getElementById('cpu-val').innerText = this.value" class="w-full accent-blue-500 bg-slate-800 rounded-lg">
        </div>
        <div>
          <label class="text-xs font-semibold text-slate-300 block mb-1">Target Memory (<span id="ram-val">8192</span> MB / <span id="ram-gb-val">8</span> GB)</label>
          <input type="range" id="resize-ram" min="1024" max="65536" step="1024" value="8192" oninput="document.getElementById('ram-val').innerText = this.value; document.getElementById('ram-gb-val').innerText = (this.value/1024).toFixed(0)" class="w-full accent-blue-500 bg-slate-800 rounded-lg">
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
        <button onclick="closeResizeModal()" class="px-4 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition">Cancel</button>
        <button onclick="submitResize()" class="px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition">Apply Resize</button>
      </div>
    </div>
  </div>

  <!-- Deploy VM Modal -->
  <div id="deploy-modal" class="hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-dark-900 border border-slate-700 rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
      <h3 class="text-lg font-bold text-white flex items-center gap-2">
        <span>🚀</span> Deploy Virtual Machine
      </h3>
      <p class="text-xs text-slate-400">Clone and customize a new instance from templates.</p>

      <div class="space-y-3 pt-2">
        <div>
          <label class="text-xs font-semibold text-slate-300 block mb-1">Target Cluster</label>
          <select id="deploy-cluster" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
            <option value="local-kvm-hardware">⚡ local-kvm-hardware (Real /dev/kvm on this machine)</option>
            <option value="proxmox-zone-a">proxmox-zone-a (Simulated KVM)</option>
            <option value="vmware-zone-b">vmware-zone-b (Simulated vSphere)</option>
          </select>
        </div>
        <div>
          <label class="text-xs font-semibold text-slate-300 block mb-1">VM Name</label>
          <input type="text" id="deploy-name" placeholder="real-local-vm-01" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
        </div>
        <div>
          <label class="text-xs font-semibold text-slate-300 block mb-1">Template / Disk</label>
          <select id="deploy-template" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
            <option value="/home/devesh/gpos_koji/eel9-guest.qcow2">Enterprise Linux 9 (Local qcow2 Fast-COW)</option>
            <option value="blank">Blank QEMU Drive (10 GB)</option>
            <option value="9000">Cloud-Init Gold Template (9000)</option>
          </select>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs font-semibold text-slate-300 block mb-1">Cores</label>
            <input type="number" id="deploy-cpu" value="4" min="1" max="32" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
          </div>
          <div>
            <label class="text-xs font-semibold text-slate-300 block mb-1">RAM (MB)</label>
            <input type="number" id="deploy-ram" value="8192" min="1024" step="1024" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
        <button onclick="closeDeployModal()" class="px-4 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition">Cancel</button>
        <button onclick="submitDeploy()" class="px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition">Deploy Instance</button>
      </div>
    </div>
  </div>

  <script>
    async function fetchInventory() {
      const spinner = document.getElementById('loading-spinner');
      spinner.classList.remove('hidden');
      try {
        const res = await fetch('/api/v1/vms');
        const data = await res.json();
        renderTable(data);
      } catch (err) {
        console.error('Failed to fetch VMs:', err);
      } finally {
        spinner.classList.add('hidden');
      }
    }

    function renderTable(vms) {
      const tbody = document.getElementById('vm-table-body');
      tbody.innerHTML = '';

      let runningCount = 0;
      let totalCores = 0;
      let totalRam = 0;

      vms.forEach(vm => {
        const isRunning = vm.status === 'running';
        if (isRunning) runningCount++;
        totalCores += (vm.cpu_cores || 0);
        totalRam += (vm.memory_mb || 0);

        const row = document.createElement('tr');
        row.className = 'hover:bg-slate-800/40 transition';

        const hypBadge = vm.hypervisor === 'proxmox'
          ? '<span class="px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">Proxmox KVM</span>'
          : (vm.hypervisor === 'vmware'
            ? '<span class="px-2 py-0.5 rounded text-[11px] font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">vSphere 8</span>'
            : '<span class="px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Bare-Metal KVM</span>');

        const statusBadge = isRunning
          ? '<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 status-running"></span>Running</span>'
          : '<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20"><span class="w-1.5 h-1.5 rounded-full bg-rose-400"></span>Stopped</span>';

        const toggleBtn = isRunning
          ? `<button onclick="togglePower('${vm.cluster}', '${vm.vm_id}', 'stop')" class="px-2.5 py-1 rounded text-xs font-medium bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 transition">Stop</button>`
          : `<button onclick="togglePower('${vm.cluster}', '${vm.vm_id}', 'start')" class="px-2.5 py-1 rounded text-xs font-medium bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 transition">Start</button>`;

        row.innerHTML = `
          <td class="px-6 py-4">
            <div class="font-semibold text-white">${vm.name}</div>
            <div class="text-xs text-slate-500 font-mono">ID: ${vm.vm_id}</div>
          </td>
          <td class="px-6 py-4">${hypBadge}</td>
          <td class="px-6 py-4 text-xs font-mono text-slate-400">${vm.cluster}</td>
          <td class="px-6 py-4">${statusBadge}</td>
          <td class="px-6 py-4 font-mono">${vm.cpu_cores}</td>
          <td class="px-6 py-4 font-mono">${(vm.memory_mb/1024).toFixed(1)} GB</td>
          <td class="px-6 py-4 text-right space-x-2">
            ${toggleBtn}
            <button onclick="openResizeModal('${vm.cluster}', '${vm.vm_id}', ${vm.cpu_cores}, ${vm.memory_mb})" class="px-2.5 py-1 rounded text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">Resize</button>
          </td>
        `;
        tbody.appendChild(row);
      });

      document.getElementById('stat-total-vms').innerText = vms.length;
      document.getElementById('stat-running-vms').innerText = runningCount;
      document.getElementById('stat-resources').innerText = `${totalCores} vCPU / ${(totalRam/1024).toFixed(0)} GB`;
    }

    async function togglePower(cluster, vmId, action) {
      await fetch(`/api/v1/vms/${cluster}/${vmId}/${action}`, { method: 'POST' });
      await fetchInventory();
    }

    function openResizeModal(cluster, vmId, currentCpu, currentRam) {
      document.getElementById('resize-cluster').value = cluster;
      document.getElementById('resize-vmid').value = vmId;
      document.getElementById('resize-cpu').value = currentCpu || 4;
      document.getElementById('cpu-val').innerText = currentCpu || 4;
      document.getElementById('resize-ram').value = currentRam || 8192;
      document.getElementById('ram-val').innerText = currentRam || 8192;
      document.getElementById('ram-gb-val').innerText = ((currentRam || 8192) / 1024).toFixed(0);
      document.getElementById('resize-modal').classList.remove('hidden');
    }

    function closeResizeModal() {
      document.getElementById('resize-modal').classList.add('hidden');
    }

    async function submitResize() {
      const cluster = document.getElementById('resize-cluster').value;
      const vmId = document.getElementById('resize-vmid').value;
      const cpu = parseInt(document.getElementById('resize-cpu').value);
      const ram = parseInt(document.getElementById('resize-ram').value);

      closeResizeModal();
      await fetch(`/api/v1/vms/${cluster}/${vmId}/resize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cpu_cores: cpu, memory_mb: ram })
      });
      await fetchInventory();
    }

    function openDeployModal() {
      document.getElementById('deploy-modal').classList.remove('hidden');
    }

    function closeDeployModal() {
      document.getElementById('deploy-modal').classList.add('hidden');
    }

    async function submitDeploy() {
      const cluster = document.getElementById('deploy-cluster').value;
      const name = document.getElementById('deploy-name').value || 'new-workload-01';
      const template = document.getElementById('deploy-template').value;
      const cpu = parseInt(document.getElementById('deploy-cpu').value);
      const ram = parseInt(document.getElementById('deploy-ram').value);

      closeDeployModal();
      await fetch(`/api/v1/vms/${cluster}/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, template_id: template, cpu_cores: cpu, memory_mb: ram })
      });
      await fetchInventory();
    }

    // Initial load & automatic polling every 8s
    fetchInventory();
    setInterval(fetchInventory, 8000);
  </script>
</body>
</html>
"""


def create_dashboard_app(client: MultiHypervisorClient) -> FastAPI:
    app = FastAPI(title="Multi-Hypervisor Dashboard")

    @app.get("/", response_class=HTMLResponse)
    @app.head("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(content=HTML_TEMPLATE)

    @app.get("/api/v1/clusters")
    def list_clusters():
        return {"clusters": client.clusters}

    @app.get("/api/v1/vms")
    def list_vms():
        results = []
        for cluster_name in client.clusters:
            adapter = client.get_adapter(cluster_name)
            for vm in adapter.list_vms():
                d = vm.model_dump()
                d["cluster"] = cluster_name
                results.append(d)
        return results

    @app.post("/api/v1/vms/{cluster_name}/{vm_id}/start")
    def start_vm(cluster_name: str, vm_id: str):
        res = client.start_vm(cluster_name, vm_id)
        return {"status": "ok", "task_id": res.task_id}

    @app.post("/api/v1/vms/{cluster_name}/{vm_id}/stop")
    def stop_vm(cluster_name: str, vm_id: str):
        res = client.stop_vm(cluster_name, vm_id, force=True)
        return {"status": "ok", "task_id": res.task_id}

    @app.post("/api/v1/vms/{cluster_name}/{vm_id}/resize")
    def resize_vm(cluster_name: str, vm_id: str, req: VMResizeRequest):
        res = client.resize_vm(cluster_name, vm_id, req)
        return {"status": "ok", "message": res.message}

    @app.post("/api/v1/vms/{cluster_name}/deploy")
    def deploy_vm(cluster_name: str, req: VMCreateRequest):
        res = client.create_vm(cluster_name, req)
        return {"status": "ok", "vm_id": res.vm_id, "task_id": res.task_id}

    return app


def main():
    parser = argparse.ArgumentParser(description="Multi-Hypervisor Web Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard port (default: 8000)")
    parser.add_argument("--sim-port", type=int, default=8006, help="Internal simulator port (default: 8006)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    args = parser.parse_args()

    # 1. Start simulator in background thread for zero-config local testing
    sim_app = create_simulator_app()
    sim_server = uvicorn.Server(uvicorn.Config(sim_app, host=args.host, port=args.sim_port, log_level="error"))
    sim_thread = threading.Thread(target=sim_server.run, daemon=True)
    sim_thread.start()
    time.sleep(0.4)

    # 2. Wire up MultiHypervisorClient
    client = MultiHypervisorClient()

    # Try registering real local KVM hardware if available
    try:
        kvm_adapter = LibvirtKvmAdapter(uri="qemu:///session")
        if kvm_adapter.ping():
            client.register("local-kvm-hardware", kvm_adapter)
            print("  ✓ Real Bare-Metal KVM registered via libvirt (qemu:///session)")
    except Exception as e:
        print(f"  (Real local KVM not active: {e})")

    client.register(
        "proxmox-zone-a",
        ProxmoxAdapter(
            endpoint=f"http://{args.host}:{args.sim_port}",
            token_id="root@pam!token",
            token_secret="dummy",
            verify_ssl=False,
        ),
    )
    client.register(
        "vmware-zone-b",
        VMwareAdapter(
            endpoint=f"http://{args.host}:{args.sim_port}",
            username="admin@vsphere.local",
            password="pwd",
            verify_ssl=False,
        ),
    )

    print(f"\n" + "=" * 65)
    print(f"🚀 Multi-Hypervisor Dashboard is LIVE!")
    print(f"👉 Open in your browser: http://{args.host}:{args.port}")
    print(f"=" * 65 + "\n")

    dash_app = create_dashboard_app(client)
    uvicorn.run(dash_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
