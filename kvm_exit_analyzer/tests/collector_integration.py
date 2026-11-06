"""Explicit Linux/root integration check; excluded from unittest discovery. No VM."""
import json
import subprocess
import sys
from pathlib import Path

project = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project / 'kvm_exit_analyzer'))
from trace_tid_map import TraceTidMap
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=False)
state_files = ['tracing_on', 'current_tracer', 'trace_clock', 'set_event']
before = {name: Path('/sys/kernel/tracing', name).read_text() for name in state_files}
code = '''import os, signal, time, sys
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
with open(sys.argv[1], 'w') as f: f.write(f'hypervisor_tid={os.getpid()}')
print(os.getpid(), flush=True)
signal.sigwait({signal.SIGUSR1})
for i in range(40): time.sleep(0.01)
'''
mapper = TraceTidMap().__enter__()
proc = subprocess.Popen([sys.executable, '-c', code, str(mapper.marker)], stdout=subprocess.PIPE, text=True)
try:
    pid = int(proc.stdout.readline())
    mapping = mapper.resolve([pid])
    (output / 'thread-map.json').write_text(json.dumps(mapping, indent=2))
    with (output / 'collector.log').open('w') as log:
        subprocess.run(['bash', str(project / 'kvm_exit_analyzer/collect_kvm_trace.sh'), '--pid', str(pid),
                        '--seconds', '1', '--output', str(output / 'capture'), '--signal-start',
                        '--trace-tids', str(mapping[pid])],
                       check=True, timeout=40, stdout=log, stderr=subprocess.STDOUT)
    assert proc.wait(timeout=5) == 0
    text = (output / 'capture/trace.txt').read_text()
    assert 'sched_switch:' in text and 'sched_wakeup:' in text, 'no scheduler events recorded'
    after = {name: Path('/sys/kernel/tracing', name).read_text() for name in state_files}
    (output / 'tracefs-state.json').write_text(json.dumps({'before': before, 'after': after}, indent=2))
    assert before == after, 'top-level tracing configuration changed'
    print('PASS: real collector PID mapping, start synchronization, scheduler capture, top-level trace state preserved')
finally:
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    mapper.__exit__(None, None, None)
