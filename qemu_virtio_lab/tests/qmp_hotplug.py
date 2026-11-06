#!/usr/bin/env python3
"""Exercise PCIe add/remove with acknowledgement by a real Linux Guest kernel."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kvm_exit_analyzer'))
from linux_guest import LinuxGuest


def inventory(guest):
    guest.serial.sendall(b'inventory 0 0\n')
    lines = guest.read_until('LAB_DONE', 10)
    assert lines[-1] == 'LAB_DONE 0'
    return int(next(line.split()[1] for line in lines if line.startswith('LAB_DEVICES ')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 1000: parser.error('cycles 1..1000')
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with LinuxGuest(args.qemu, args.assets, args.out / 'guest', vcpus=1, map_tids=False) as guest:
        assert inventory(guest) == 0
        for cycle in range(args.cycles):
            ident = f'lab{cycle}'
            began = time.monotonic()
            guest.qmp('device_add', {'driver': 'virtio-lab-pci', 'id': ident, 'bus': 'labport'})
            deadline = time.monotonic() + 15
            while inventory(guest) != 1:
                if time.monotonic() > deadline: raise TimeoutError('Guest did not enumerate lab PCI device')
                time.sleep(.1)
            enumerated = time.monotonic()
            guest.qmp('device_del', {'id': ident})
            deadline = time.monotonic() + 15
            while True:
                guest.qmp('query-status')  # also receives queued asynchronous events
                removed = any(event['event'] == 'DEVICE_DELETED' and event.get('data', {}).get('device') == ident
                              for event in guest.events)
                if removed and inventory(guest) == 0:
                    break
                if time.monotonic() > deadline: raise TimeoutError('Guest did not acknowledge device removal')
                time.sleep(.1)
            row = {'cycle': cycle + 1, 'enumeration_seconds': enumerated - began,
                   'removal_seconds': time.monotonic() - enumerated}
            rows.append(row)
            (args.out / 'cycles.json').write_text(json.dumps(rows, indent=2))
            print(json.dumps(row), flush=True)
        # Confirm the OS still executes a normal userspace workload afterwards.
        result = guest.workload('cpu', 1, 1)
        (args.out / 'summary.json').write_text(json.dumps({
            'result': 'PASS', 'cycles': len(rows), 'guest_recovery': result,
            'scope': 'Linux standard PCIe hotplug/virtio-pci transport; no virtio-lab Guest function driver',
        }, indent=2))


if __name__ == '__main__': main()
