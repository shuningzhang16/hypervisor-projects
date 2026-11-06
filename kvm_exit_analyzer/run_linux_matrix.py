#!/usr/bin/env python3
"""Bounded Linux Guest CPU/disk/TCP experiments, using existing standard drivers."""
import argparse
import json
import socketserver
import subprocess
import threading
import time
from pathlib import Path
from analyze_trace import analyze, parse_line
from linux_guest import LinuxGuest


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        while True:
            data = self.request.recv(65536)
            if not data:
                break
            self.request.sendall(data)


class EchoServer(socketserver.ThreadingTCPServer):
    daemon_threads = True


def record_run(guest, directory, mode, seconds, parameter, traced):
    directory.mkdir()
    collector = None
    log = (directory / 'collector.console').open('w')
    try:
        if traced:
            command = ['bash', str(Path(__file__).with_name('collect_kvm_trace.sh')),
                       '--pid', str(guest.proc.pid), '--trace-tids', ','.join(map(str, guest.tid_map.values())),
                       '--seconds', str(seconds + 3), '--output', str(directory / 'trace'),
                       '--ready-file', str(directory / 'trace-ready')]
            (directory / 'collector-command.json').write_text(json.dumps(command))
            collector = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 15
            while not (directory / 'trace-ready').exists():
                if collector.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Collector did not become ready; inspect collector.console')
                time.sleep(.02)
        start = time.monotonic_ns()
        result = guest.workload(mode, seconds, parameter)
        end = time.monotonic_ns()
        result.update(traced=traced, host_start_ns=start, host_end_ns=end)
        (directory / 'workload.json').write_text(json.dumps(result, indent=2))
        if collector:
            if collector.wait(timeout=40):
                raise RuntimeError('Collector failed')
            trace = directory / 'trace'
            if 'trace_clock=mono\n' not in (trace / 'metadata.txt').read_text():
                raise RuntimeError('Monotonic trace clock required for workload window')
            # Preserve the full recording, and analyze only the host command/reply window.
            # Keep unknown/loss lines so clipping never hides parsing or loss diagnostics.
            with (trace / 'trace.txt').open() as source, (directory / 'workload-trace.txt').open('w') as out:
                for line in source:
                    event = parse_line(line)
                    if event is None or start <= event.ns <= end:
                        out.write(line)
            summary = analyze(directory / 'workload-trace.txt', directory / 'analysis',
                              set(guest.tid_map.values()), source_kind='real-kvm',
                              diagnostics=[trace / 'collection.log', trace / 'report.stderr'])
            result['kvm_exits'] = summary['event_counts'].get('kvm_exit', 0)
            result['timing_degraded'] = summary['timing_degraded']
            if not result['kvm_exits'] or summary['timing_degraded']:
                raise RuntimeError('Empty or degraded trace; retain evidence and stop')
        (directory / 'result.json').write_text(json.dumps(result, indent=2))
        return result
    finally:
        if collector and collector.poll() is None:
            collector.terminate()
            try: collector.wait(timeout=10)
            except subprocess.TimeoutExpired:
                collector.kill(); collector.wait()
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=3)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--smoke', action='store_true', help='one traced disk + network run')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30 or not 1 <= args.repeats <= 10:
        parser.error('seconds 1..30; repeats 1..10')
    args.out.mkdir(parents=True, exist_ok=False)
    configurations = [
        ('vcpu2-mem256', 2, 256, 'virtio', 'virtio', ['cpu', 'disk', 'net']),
        ('vcpu1-mem256', 1, 256, 'virtio', 'virtio', ['cpu']),
        ('vcpu4-mem256', 4, 256, 'virtio', 'virtio', ['cpu']),
        ('vcpu2-mem512', 2, 512, 'virtio', 'virtio', ['cpu']),
        ('ahci', 2, 256, 'ahci', 'virtio', ['disk']),
        ('e1000', 2, 256, 'virtio', 'e1000', ['net']),
    ]
    if args.smoke:
        configurations = [('smoke', 2, 256, 'virtio', 'virtio', ['disk', 'net'])]
    (args.out / 'experiment.json').write_text(json.dumps({
        'seconds': args.seconds, 'repeats': args.repeats, 'configurations': configurations,
        'smoke': args.smoke,
        'source_kind': 'real Linux Guest, WSL2 nested KVM',
        'order': 'alternate trace-off/on and trace-on/off by repeat',
        'window': 'host CLOCK_MONOTONIC command-send to complete-reply; includes serial overhead',
    }, indent=2))
    with EchoServer(('127.0.0.1', 0), Echo) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for name, cpus, memory, disk, nic, modes in configurations:
                directory = args.out / name
                with LinuxGuest(args.qemu, args.assets, directory / 'boot', vcpus=cpus,
                                memory=memory, disk=disk, nic=nic) as guest:
                    for mode in modes:
                        parameter = server.server_address[1] if mode == 'net' else cpus
                        # Warm-up is explicitly unmeasured and kept in serial evidence.
                        guest.workload(mode, 1, parameter)
                        for repeat in range(1 if args.smoke else args.repeats):
                            states = [True] if args.smoke else ([False, True] if repeat % 2 == 0 else [True, False])
                            for traced in states:
                                run = directory / f'{mode}-r{repeat + 1}-trace{int(traced)}'
                                result = record_run(guest, run, mode, args.seconds, parameter, traced)
                                result.update(configuration=name, vcpus=cpus, memory_mib=memory,
                                              disk=disk, nic=nic, repeat=repeat + 1)
                                (run / 'result.json').write_text(json.dumps(result, indent=2))
                                print(json.dumps({'run': str(run.relative_to(args.out)), **result}), flush=True)
        finally:
            server.shutdown()


if __name__ == '__main__':
    main()
