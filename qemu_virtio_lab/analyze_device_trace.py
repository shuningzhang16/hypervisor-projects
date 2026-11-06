#!/usr/bin/env python3
"""Export device completion trace records and exact quantiles; stdlib only."""
import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

COMPLETE = re.compile(r'virtio_lab_complete .*?id=(\d+) status=(\d+) used=(\d+) notify_to_complete_ns=(\d+)')


def analyze(source, output, label):
    output.mkdir(parents=True, exist_ok=False)
    durations = defaultdict(list)
    with source.open() as stream, (output / 'completions.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['request_id', 'status', 'used_bytes', 'notify_to_complete_ns'])
        for line in stream:
            match = COMPLETE.search(line)
            if match:
                request_id, status, used, ns = map(int, match.groups())
                writer.writerow([request_id, status, used, ns])
                durations[status].append(ns)
    if not durations:
        raise ValueError('no virtio_lab_complete records')
    stats = {}
    for status, values in sorted(durations.items()):
        values.sort()
        stats[status] = {'count': len(values), 'mean_ns': sum(values) / len(values), 'min_ns': values[0],
                         'max_ns': values[-1], **{f'p{p}_ns': values[math.ceil(p / 100 * len(values)) - 1]
                                              for p in (50, 95, 99)}}
    result = {'source': str(source), 'label': label, 'by_status': stats,
              'notes': ['These are backend callback-to-completion observations; not Guest end-to-end latency.',
                        'Batching and enabled trace logging affect these durations.',
                        'TCG/qtest timing cannot represent KVM performance.']}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--label', required=True, help='state workload, accelerator and logging context')
    args = parser.parse_args()
    print(json.dumps(analyze(args.trace, args.out, args.label), ensure_ascii=False, indent=2))
