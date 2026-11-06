#!/usr/bin/env python3
"""Test machine reset and the existing migration refusal through real QMP + qtest."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from qtest_smoke import QTest, connect, exercise

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('qemu', type=Path)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
with tempfile.TemporaryDirectory(prefix='lab-lifecycle-') as tmp:
    directory = Path(tmp)
    command = [str(args.qemu.resolve()), '-machine', 'q35,accel=tcg', '-m', '64', '-S',
               '-nodefaults', '-display', 'none', '-device', 'virtio-lab-pci,addr=4.0',
               '-qtest', f'unix:{directory}/qtest,server=on,wait=off', '-qtest-log', '/dev/null',
               '-qmp', f'unix:{directory}/qmp,server=on,wait=off']
    (args.out / 'command.json').write_text(json.dumps(command, indent=2))
    with (args.out / 'stderr.log').open('w') as err, (args.out / 'qmp.jsonl').open('w') as log:
        proc = subprocess.Popen(command, stderr=err, stdout=subprocess.DEVNULL)
        sockets = []
        try:
            test_socket = connect(directory / 'qtest', proc)
            sockets.append(test_socket)
            monitor = connect(directory / 'qmp', proc)
            sockets.append(monitor)
            stream = monitor.makefile('rwb', buffering=0)
            log.write(stream.readline().decode())
            def qmp(execute, arguments=None):
                request = {'execute': execute}
                if arguments is not None:
                    request['arguments'] = arguments
                line = json.dumps(request) + '\n'
                log.write(line); log.flush()
                stream.write(line.encode())
                while True:
                    line = stream.readline().decode()
                    if not line:
                        raise RuntimeError('QMP closed before response')
                    log.write(line); log.flush()
                    response = json.loads(line)
                    if 'return' in response or 'error' in response:
                        return response
            assert 'return' in qmp('qmp_capabilities')
            test = QTest(test_socket)
            exercise(test)
            assert 'return' in qmp('system_reset')
            exercise(test)
            refused = qmp('migrate', {'uri': f'unix:{directory}/unused-migration-target'})
            assert 'error' in refused and 'virtio-lab' in str(refused) and 'migrat' in str(refused).lower()
            assert 'return' in qmp('quit')
            assert proc.wait(timeout=10) == 0
            (args.out / 'result.txt').write_text('PASS: QMP system_reset + queue recovery; unmigratable device refused migration; clean quit\n')
            print('PASS: QMP machine reset, queue recovery, migration refusal, clean exit')
        finally:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
            for sock in sockets:
                sock.close()
