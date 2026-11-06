"""Resolve cooperating workload TIDs using an owned trace_marker instance.

WSL exposes a nested /proc PID view while tracepoint fields contain outer TIDs.
Each target thread writes its visible TID to this marker before the run starts.
No system-wide scheduler collection, namespace entry or task renaming is needed.
"""
import os
import re
from pathlib import Path


class TraceTidMap:
    def __enter__(self):
        root = next((p for p in (Path('/sys/kernel/tracing'), Path('/sys/kernel/debug/tracing'))
                     if (p / 'available_events').exists()), None)
        if root is None:
            raise RuntimeError('tracefs is unavailable')
        self.path = root / 'instances' / f'lab-tid-map-{os.getpid()}'
        self.path.mkdir()
        (self.path / 'tracing_on').write_text('1')
        self.marker = self.path / 'trace_marker'
        return self

    def resolve(self, tids):
        mapping = {}
        text = (self.path / 'trace').read_text()
        for line in text.splitlines():
            match = re.search(r'-(\d+)\s+\[\d+\].*hypervisor_tid=(\d+)', line)
            if match:
                mapping[int(match[2])] = int(match[1])
        if any(tid not in mapping for tid in tids):
            raise RuntimeError(f'missing thread markers for {set(tids) - mapping.keys()}')
        return {tid: mapping[tid] for tid in tids}

    def __exit__(self, *args):
        self.path.rmdir()  # tracefs removes virtual files with the owned instance.
