#!/usr/bin/env python3
"""
Example: Managing multiple Proxmox and VMware clusters with MultiHypervisorClient.
"""

from hypervisor_adapter import (
    MultiHypervisorClient,
    ProxmoxAdapter,
    VMCreateRequest,
    VMResizeRequest,
    VMwareAdapter,
)


def main():
    client = MultiHypervisorClient()

    # 1. Register a Proxmox cluster (using API Token)
    proxmox_cluster = ProxmoxAdapter(
        endpoint="https://pve1.internal.datacenter:8006",
        token_id="root@pam!swaraj_token",
        token_secret="11111111-2222-3333-4444-555555555555",
        verify_ssl=False,
    )
    client.register("kvm-zone-a", proxmox_cluster)

    # 2. Register a VMware vCenter cluster (using credentials)
    vmware_cluster = VMwareAdapter(
        endpoint="https://vcenter.internal.datacenter",
        username="administrator@vsphere.local",
        password="EnterprisePassword123!",
        verify_ssl=False,
    )
    client.register("vmware-zone-b", vmware_cluster)

    print("Registered clusters:", client.clusters)

    # 3. List all VMs across all clusters uniformly
    print("\n--- Listing all VMs across both KVM and VMware ---")
    all_vms = client.list_vms()
    for vm in all_vms:
        print(f"[{vm.hypervisor.value.upper()}] ID={vm.vm_id} | Name={vm.name} | Status={vm.status.value} | Cores={vm.cpu_cores} | RAM={vm.memory_mb}MB")

    # 4. Perform operations through cluster target
    # Start VM on KVM
    # client.start_vm("kvm-zone-a", "105")

    # Resize VM on VMware
    # client.resize_vm("vmware-zone-b", "vm-2048", VMResizeRequest(cpu_cores=8, memory_mb=16384))


if __name__ == "__main__":
    main()
