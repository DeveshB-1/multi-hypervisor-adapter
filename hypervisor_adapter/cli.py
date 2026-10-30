from __future__ import annotations

import argparse
import json
import os
import sys

from hypervisor_adapter import LibvirtKvmAdapter, ProxmoxAdapter, VMwareAdapter, VMResizeRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Hypervisor Adapter CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Global options on subparsers
    for sub in ["list", "get", "start", "stop", "resize", "delete"]:
        p = subparsers.add_parser(sub, help=f"{sub} operation")
        p.add_argument("--type", choices=["proxmox", "vmware", "kvm"], required=True, help="Hypervisor type")
        p.add_argument("--endpoint", default=os.getenv("HYPERVISOR_ENDPOINT"), help="API Endpoint URL or libvirt URI")
        p.add_argument("--username", default=os.getenv("HYPERVISOR_USER"), help="Username / Token ID")
        p.add_argument("--password", default=os.getenv("HYPERVISOR_PASSWORD"), help="Password / Token Secret")
        p.add_argument("--token-id", default=os.getenv("PROXMOX_TOKEN_ID"), help="Proxmox Token ID (USER@REALM!TOKEN)")
        p.add_argument("--token-secret", default=os.getenv("PROXMOX_TOKEN_SECRET"), help="Proxmox Token UUID")
        p.add_argument("--insecure", action="store_true", default=True, help="Ignore self-signed SSL warnings")

        if sub in ["get", "start", "stop", "resize", "delete"]:
            p.add_argument("vm_id", help="Virtual Machine ID")
        if sub == "stop":
            p.add_argument("--force", action="store_true", help="Hard power-off")
        if sub == "resize":
            p.add_argument("--cpu", type=int, help="Target vCPU cores")
            p.add_argument("--ram", type=int, help="Target RAM in MiB")

    args = parser.parse_args()

    # Instantiate adapter
    if args.type == "kvm":
        uri = args.endpoint or "qemu:///session"
        adapter = LibvirtKvmAdapter(uri=uri)
    elif args.type == "proxmox":
        if not args.endpoint:
            print("Error: --endpoint or HYPERVISOR_ENDPOINT is required", file=sys.stderr)
            sys.exit(1)
        adapter = ProxmoxAdapter(
            endpoint=args.endpoint,
            token_id=args.token_id,
            token_secret=args.token_secret,
            username=args.username,
            password=args.password,
            verify_ssl=not args.insecure,
        )
    else:
        if not args.endpoint:
            print("Error: --endpoint or HYPERVISOR_ENDPOINT is required", file=sys.stderr)
            sys.exit(1)
        if not args.username or not args.password:
            print("Error: --username and --password are required for VMware vCenter", file=sys.stderr)
            sys.exit(1)
        adapter = VMwareAdapter(
            endpoint=args.endpoint,
            username=args.username,
            password=args.password,
            verify_ssl=not args.insecure,
        )

    try:
        if args.command == "list":
            vms = adapter.list_vms()
            print(f"{'ID':<15} {'NAME':<30} {'STATUS':<12} {'CPU':<6} {'RAM (MB)':<10}")
            print("-" * 75)
            for vm in vms:
                print(f"{vm.vm_id:<15} {vm.name:<30} {vm.status.value:<12} {vm.cpu_cores:<6} {vm.memory_mb:<10}")

        elif args.command == "get":
            vm = adapter.get_vm(args.vm_id)
            print(json.dumps(vm.model_dump(), indent=2))

        elif args.command == "start":
            res = adapter.start_vm(args.vm_id)
            print(f"Success: {res.message} (Task: {res.task_id})")

        elif args.command == "stop":
            res = adapter.stop_vm(args.vm_id, force=args.force)
            print(f"Success: {res.message} (Task: {res.task_id})")

        elif args.command == "resize":
            res = adapter.resize_vm(args.vm_id, VMResizeRequest(cpu_cores=args.cpu, memory_mb=args.ram))
            print(f"Success: {res.message}")

        elif args.command == "delete":
            res = adapter.delete_vm(args.vm_id)
            print(f"Success: {res.message}")

    except Exception as e:
        print(f"Operation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
