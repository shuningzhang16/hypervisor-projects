#!/usr/bin/env python3
"""Run bounded KVM microbench experiments and save raw trace/commands/results; no retries."""
import argparse
import json
import os
import selectors
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from trace_tid_map import TraceTidMap


def run_one(root, binary, mode, vcpus, seconds, repeat, tracing=True):
    label = f'{mode}-v{vcpus}-r{repeat}' + ('' if tracing else '-untraced')
    output = root / label
    output.mkdir()
    command = [str(binary.resolve()), '--mode', mode, '--vcpus', str(vcpus),
               '--seconds', str(seconds), '--delay-ms', '0', '--pause-us', '1000',
               '--wait-signal', '1' if tracing else '0']
    with (TraceTidMap() if tracing else nullcontext()) as mapper, (output / 'workload.stderr').open('w') as err:
        if mapper:
            command += ['--trace-marker', str(mapper.marker)]
        (output / 'workload-command.json').write_text(json.dumps(command, indent=2) + '\n')
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(10):
                    raise TimeoutError('workload did not become ready')
                ready_line = process.stdout.readline()
            (output / 'workload.jsonl').write_text(ready_line)
            ready = json.loads(ready_line)
            if ready.get('state') != 'ready':
                raise RuntimeError('workload readiness failed')
            if tracing:
                mapping = mapper.resolve(ready['tids'])
                (output / 'thread-map.json').write_text(json.dumps(mapping, indent=2) + '\n')
                collector = Path(__file__).with_name('collect_kvm_trace.sh')
                with (output / 'collector-console.log').open('w') as log:
                    subprocess.run(['bash', str(collector), '--pid', str(ready['pid']), '--seconds',
                                    str(seconds + 1), '--output', str(output / 'capture'), '--signal-start',
                                    '--trace-tids', ','.join(map(str, mapping.values()))],
                                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=seconds + 30)
            rest, _ = process.communicate(timeout=seconds + 15)
            with (output / 'workload.jsonl').open('a') as log:
                log.write(rest)
            if process.returncode:
                raise RuntimeError(f'KVM workload failed: exit={process.returncode}; no automatic retry')
            finished = json.loads(rest.splitlines()[-1])
            if any(w['error'] for w in finished['workers']):
                raise RuntimeError('KVM worker reported failure')
            if tracing:
                analyzer = Path(__file__).with_name('analyze_trace.py')
                with (output / 'analyzer-console.log').open('w') as log:
                    subprocess.run([sys.executable, str(analyzer), str(output / 'capture/trace.txt'),
                                    '--out', str(output / 'analysis'), '--source-kind', 'real-kvm-microbench',
                                    '--diagnostics', str(output / 'capture/collection.log'),
                                    '--diagnostics', str(output / 'capture/report.stderr')], stdout=log,
                                   stderr=subprocess.STDOUT, check=True)
            (output / 'result.json').write_text(json.dumps({
                'state': 'passed', 'provenance': 'real-kvm-microbench', 'mode': mode,
                'vcpus': vcpus, 'repeat': repeat, 'tracing': tracing, 'requested_seconds': seconds,
                'workload': finished,
            }, indent=2) + '\n')
            print(f'PASS {label}', flush=True)
        except Exception as exc:
            (output / 'failure.txt').write_text(f'{type(exc).__name__}: {exc}\nNo automatic retry.\n')
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--modes', nargs='+', choices=['cpu', 'pio', 'mmio'], default=['cpu', 'pio', 'mmio'])
    parser.add_argument('--vcpus', nargs='+', type=int, choices=range(1, 5), default=[1, 2, 4])
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--seconds', type=int, choices=range(1, 31), default=2)
    parser.add_argument('--include-untraced', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('root required for tracefs access; no permission changes are made')
    args.out.mkdir(parents=True, exist_ok=False)
    for mode in args.modes:
        for vcpus in args.vcpus:
            for repeat in range(1, args.repeats + 1):
                run_one(args.out, args.binary, mode, vcpus, args.seconds, repeat)
                if args.include_untraced:
                    run_one(args.out, args.binary, mode, vcpus, args.seconds, repeat, tracing=False)


if __name__ == '__main__':
    main()
