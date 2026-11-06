#!/usr/bin/env python3
"""Bounded repeated queue/reset stress in one QEMU process, with RSS observations."""
import argparse
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from qtest_smoke import QTest, connect, exercise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600: parser.error('seconds 1..3600')
    args.out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='lab-soak-') as tmp:
        path = Path(tmp) / 'qtest'
        command = [str(args.qemu.resolve()), '-machine', 'q35,accel=tcg', '-m', '64', '-S',
                   '-nodefaults', '-display', 'none', '-device', 'virtio-lab-pci,addr=4.0',
                   '-qtest', f'unix:{path},server=on,wait=off', '-qtest-log', '/dev/null']
        (args.out / 'command.json').write_text(json.dumps(command, indent=2))
        with (args.out / 'stderr.log').open('w') as err, (args.out / 'rounds.jsonl').open('w') as log:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
            sock = None
            rows = []
            began = time.monotonic()
            try:
                sock = connect(path, proc)
                q = QTest(sock)
                while not rows or time.monotonic() - began < args.seconds:
                    result = exercise(q, requests=65568, resets=32)
                    status = Path(f'/proc/{proc.pid}/status').read_text()
                    result.update(round=len(rows) + 1, elapsed_seconds=time.monotonic() - began,
                                  rss_kib=int(re.search(r'^VmRSS:\s+(\d+)', status, re.M)[1]))
                    rows.append(result)
                    log.write(json.dumps(result) + '\n'); log.flush()
                    print(json.dumps(result), flush=True)
                summary = {'result': 'PASS', 'rounds': len(rows),
                           'requests': sum(r['requests'] for r in rows),
                           'resets': sum(r['reset_cycles'] for r in rows),
                           'index_wraps': sum(r['index_wraps'] for r in rows),
                           'elapsed_seconds': time.monotonic() - began,
                           'rss_first_kib': rows[0]['rss_kib'], 'rss_last_kib': rows[-1]['rss_kib'],
                           'rss_max_kib': max(r['rss_kib'] for r in rows),
                           'scope': 'single QEMU process, TCG qtest, trace disabled; bounded software stress, not production endurance'}
                (args.out / 'summary.json').write_text(json.dumps(summary, indent=2))
            finally:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
                if sock: sock.close()


if __name__ == '__main__': main()
