#!/usr/bin/env python3
"""Boot Linux and validate the actual virtio-lab kernel driver and userspace ABI."""
import argparse
import csv
import json
import math
import re
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kvm_exit_analyzer'))
from linux_guest import LinuxGuest


def run_command(guest, command, log, timeout=60):
    guest.serial.sendall((command + '\n').encode())
    lines = guest.read_until('LAB_DONE', timeout)
    log.write(json.dumps({'command': command, 'lines': lines}, ensure_ascii=False) + '\n'); log.flush()
    if lines[-1] != 'LAB_DONE 0':
        raise RuntimeError(f'Guest command {command!r} failed: {lines[-10:]}')
    return lines


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    packed = int(args.packed)
    extra = ['-device', f'virtio-lab-pci,id=lab,bus=labport,packed={"on" if packed else "off"}',
             '-trace', 'enable=virtio_lab_*', '-D', str(args.out / 'device-trace.log')]
    with (args.out / 'commands.jsonl').open('w') as log:
        with LinuxGuest(args.qemu, args.assets, args.out / 'guest', memory=512, map_tids=False,
                        extra_args=extra, accelerator=args.accelerator) as guest:
            state = guest.qmp('query-kvm')
            assert state['enabled'] == (args.accelerator == 'kvm')
            (args.out / 'accelerator.json').write_text(json.dumps(state, indent=2))
            results = []
            def command(text, timeout=60):
                lines = run_command(guest, text, log, timeout)
                results.extend(line for line in lines if line.startswith('LAB_PASS'))
                return lines
            command(f'smoke {packed}')
            if not args.smoke_only:
                command('concurrent')
                lines = command(f'latency {args.samples}', timeout=120)
                rows = [list(map(int, line.split(',')[1:])) for line in lines if line.startswith('LAB_LATENCY,')]
                assert len(rows) == args.samples
                fields = ['request_id', 'submit_to_callback_ns', 'submit_to_wait_return_ns', 'ioctl_roundtrip_ns']
                with (args.out / 'latencies.csv').open('w', newline='') as stream:
                    writer = csv.writer(stream); writer.writerow(fields); writer.writerows(rows)
                latency = {}
                for i, field in enumerate(fields[1:], 1):
                    values = sorted(row[i] for row in rows)
                    latency[field] = {'count': len(values), 'min': values[0], 'max': values[-1],
                                      **{f'p{p}': values[math.ceil(p / 100 * len(values)) - 1] for p in (50, 95, 99)}}
                (args.out / 'latency-summary.json').write_text(json.dumps({
                    'accelerator': args.accelerator, 'packed': packed, 'unit': 'ns', 'metrics': latency,
                    'scope': 'Guest CLOCK_MONOTONIC, 32-byte echo, QEMU backend trace logging enabled; nested KVM if selected',
                    'serial_output': 'emitted after measuring all samples',
                }, indent=2))
                for _ in range(args.cycles):
                    command('rebind'); command(f'smoke {packed}')
                for _ in range(args.cycles):
                    command('reload'); command(f'smoke {packed}')
                command('fault'); command('timeout')
                command('reload'); command(f'smoke {packed}')
                # Hold a real open char-device FD across Guest PCIe removal.
                lines = command('remove-start')
                assert 'LAB_HOLD_OPEN' in lines
                command('unload-busy')
                guest.qmp('device_del', {'id': 'lab'})
                deadline = time.monotonic() + 20
                while True:
                    guest.qmp('query-status')
                    if any(event['event'] == 'DEVICE_DELETED' and event.get('data', {}).get('device') == 'lab'
                           for event in guest.events):
                        break
                    if time.monotonic() > deadline: raise TimeoutError('PCIe removal acknowledgement')
                    time.sleep(.1)
                command('remove-result')
                guest.qmp('device_add', {'driver': 'virtio-lab-pci', 'id': 'lab2', 'bus': 'labport', 'packed': bool(packed)})
                # PCIe hotplug/probe is asynchronous; synchronize on the actual misc node.
                command('await-device', timeout=20)
                command(f'smoke {packed}')
                command('unload'); command('load'); command(f'smoke {packed}')
            kernel_log = '\n'.join(command('dmesg'))
            (args.out / 'dmesg.txt').write_text(kernel_log)
            failures = re.findall(r'(?:BUG:|WARNING:|Oops:|Kernel panic|general protection fault|KASAN:|slab-out-of-bounds)', kernel_log)
            if failures: raise RuntimeError(f'Guest kernel diagnostics: {failures}')
            (args.out / 'summary.json').write_text(json.dumps({
                'result': 'PASS', 'accelerator': args.accelerator, 'packed': bool(packed),
                'guest_kernel': '5.15.0-194-generic', 'smoke_only': args.smoke_only,
                'rebind_cycles': 0 if args.smoke_only else args.cycles,
                'reload_cycles': 0 if args.smoke_only else args.cycles,
                'latency_samples': 0 if args.smoke_only else args.samples,
                'kernel_error_markers': failures, 'checks': results,
                'module_scope': 'custom driver loaded only inside this disposable Guest; no host module loaded',
            }, indent=2))
            print(json.dumps({'result': 'PASS', 'accelerator': args.accelerator, 'packed': packed,
                              'checks': len(results), 'output': str(args.out)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--accelerator', choices=['kvm', 'tcg'], default='kvm')
    parser.add_argument('--packed', action='store_true')
    parser.add_argument('--samples', type=int, default=1000)
    parser.add_argument('--cycles', type=int, default=8)
    parser.add_argument('--smoke-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.samples <= 10000 or not 1 <= args.cycles <= 100:
        parser.error('samples 1..10000 and cycles 1..100 required')
    try:
        run(args)
    except BaseException as error:
        if args.out.exists(): (args.out / 'failure.txt').write_text(repr(error) + '\n')
        raise
