#!/usr/bin/env python3
"""Analyze timestamp-ordered `trace-cmd report -N -t` text; Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

KVM = {'kvm_entry', 'kvm_exit', 'kvm_mmio', 'kvm_pio'}
SCHED = {'sched_switch', 'sched_wakeup'}
LINE = re.compile(
    r'^\s*(?P<comm>.+)-(?P<tid>\d+)\s+(?:\(\s*\d+\)\s+)?'
    r'\[(?P<cpu>\d+)\]\s+(?:\S+\s+)?(?P<time>\d+\.\d+):\s+'
    r'(?P<event>(?:\w+:)?\w+):\s*(?P<body>.*)$'
)
LOSS = re.compile(r'(?:LOST\s+\d+\s+EVENTS|\d+\s+EVENTS?\s+(?:LOST|DROPPED)|MISSED\s+EVENTS)', re.I)


@dataclass
class Event:
    tid: int
    cpu: int
    ns: int
    name: str
    body: str


def parse_line(line: str) -> Event | None:
    match = LINE.match(line)
    if not match:
        return None
    seconds, fraction = match['time'].split('.')
    ns = int(seconds) * 1_000_000_000 + int(fraction[:9].ljust(9, '0'))
    return Event(int(match['tid']), int(match['cpu']), ns,
                 match['event'].rsplit(':', 1)[-1], match['body'])


def field(body: str, key: str) -> str | None:
    match = re.search(r'(?:^|\s)' + re.escape(key) + r'=(\S+)', body)
    return match[1] if match else None


def exit_reason(body: str) -> str:
    match = re.search(r'\breason(?:=|\s+)([A-Za-z0-9_+-]+)', body)
    return match[1] if match else 'UNKNOWN'


def analyze(source: Path, output: Path, tids: set[int] | None = None, *, source_kind='unspecified', diagnostics=()) -> dict:
    if tids is None:
        tids = set()
        with source.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                event = parse_line(line)
                if event and event.name in {'kvm_entry', 'kvm_exit'}:
                    tids.add(event.tid)
    if not tids:
        raise ValueError('No vCPU TIDs found. Use --tid for a known thread, or check input format/events.')
    output.mkdir(parents=True, exist_ok=False)
    counts: Counter = Counter()
    reasons: Counter = Counter()
    bins: Counter = Counter()
    warnings: Counter = Counter()
    for diagnostic in diagnostics:
        with Path(diagnostic).open(encoding='utf-8', errors='replace') as stream:
            warnings['external_lost_event_markers'] += sum(bool(LOSS.search(line)) for line in stream)
    stats: dict = {}
    entries: dict[int, int] = {}
    exits: dict[int, tuple[int, str]] = {}
    runnable: dict[int, tuple[int, str]] = {}
    first = last = previous = None
    vcpu_ids: dict[int, set[str]] = defaultdict(set)

    with (output / 'intervals.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['end_timestamp_ns', 'tid', 'metric', 'duration_ns', 'exit_reason'])

        def sample(event: Event, tid: int, start: int, metric: str, reason: str = ''):
            duration = event.ns - start
            if duration < 0:
                warnings['negative_interval_discarded'] += 1
                return
            writer.writerow([event.ns, tid, metric, duration, reason])
            row = stats.setdefault((tid, metric), {'count': 0, 'sum_ns': 0, 'min_ns': duration, 'max_ns': duration})
            row['count'] += 1
            row['sum_ns'] += duration
            row['min_ns'] = min(row['min_ns'], duration)
            row['max_ns'] = max(row['max_ns'], duration)

        def clear_pairs():
            entries.clear()
            exits.clear()
            runnable.clear()

        with source.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                if LOSS.search(line):
                    warnings['lost_event_markers'] += 1
                    clear_pairs()
                    continue
                event = parse_line(line)
                if event is None:
                    if any(name + ':' in line for name in KVM | SCHED):
                        warnings['unparsed_target_lines'] += 1
                        clear_pairs()
                    continue
                if event.name not in KVM | SCHED:
                    continue
                if previous is not None and event.ns < previous:
                    warnings['out_of_order_events'] += 1
                    clear_pairs()
                previous = event.ns
                if event.name in KVM:
                    relevant = event.tid in tids
                else:
                    try:
                        if event.name == 'sched_switch':
                            prev_tid = int(field(event.body, 'prev_pid') or '')
                            next_tid = int(field(event.body, 'next_pid') or '')
                            state = field(event.body, 'prev_state')
                            if state is None:
                                raise ValueError('missing prev_state')
                            relevant = prev_tid in tids or next_tid in tids
                        else:
                            wake_tid = int(field(event.body, 'pid') or '')
                            relevant = wake_tid in tids
                    except ValueError:
                        warnings['malformed_sched_events'] += 1
                        runnable.clear()
                        continue
                if not relevant:
                    continue
                first = event.ns if first is None else min(first, event.ns)
                last = event.ns if last is None else max(last, event.ns)
                counts[event.name] += 1
                # Absolute bins avoid re-basing data if an invalid input is out of order.
                bins[(event.ns // 1_000_000_000, event.name)] += 1
                if event.name == 'kvm_entry':
                    match = re.search(r'\bvcpu(?:_id=|\s+)(\d+)', event.body)
                    if match:
                        vcpu_ids[event.tid].add(match[1])
                    if event.tid in exits:
                        start, reason = exits.pop(event.tid)
                        sample(event, event.tid, start, 'exit_to_entry_wall', reason)
                    if event.tid in entries:
                        warnings['entry_without_exit'] += 1
                    entries[event.tid] = event.ns
                elif event.name == 'kvm_exit':
                    reason = exit_reason(event.body)
                    # ISA kept separate: VMX/SVM numeric codes are not interchangeable.
                    isa_match = re.search(r'\bisa(?:=|\s+)(\w+)', event.body)
                    isa = isa_match[1] if isa_match else 'unspecified'
                    reasons[(event.tid, isa, reason)] += 1
                    if event.tid in entries:
                        sample(event, event.tid, entries.pop(event.tid), 'entry_to_exit_wall', reason)
                    else:
                        warnings['exit_without_entry'] += 1
                    if event.tid in exits:
                        warnings['exit_without_reentry'] += 1
                    exits[event.tid] = (event.ns, reason)
                elif event.name == 'sched_wakeup':
                    if field(event.body, 'success') != '0':
                        runnable.setdefault(wake_tid, (event.ns, 'wakeup_to_run'))
                elif event.name == 'sched_switch':
                    if next_tid in runnable:
                        start, metric = runnable.pop(next_tid)
                        sample(event, next_tid, start, metric)
                    if prev_tid in tids and prev_tid != next_tid:
                        if state in {'R', 'R+', '0', '0x0'}:
                            runnable[prev_tid] = (event.ns, 'preempt_to_run')
                        else:
                            runnable.pop(prev_tid, None)

    warnings['trailing_entry_without_exit'] += len(entries)
    warnings['trailing_exit_without_entry'] += len(exits)
    warnings['trailing_runnable_without_switch'] += len(runnable)
    span_s = (last - first) / 1e9 if first is not None and last is not None else 0

    def csv_file(name, header, rows):
        with (output / name).open('w', encoding='utf-8', newline='') as stream:
            w = csv.writer(stream)
            w.writerow(header)
            w.writerows(rows)

    csv_file('event_counts.csv', ['event', 'count', 'per_observed_second'],
             ((name, count, count / span_s if span_s > 0 else '') for name, count in sorted(counts.items())))
    csv_file('exit_reasons.csv', ['tid', 'isa', 'reason', 'count'],
             ((*key, count) for key, count in sorted(reasons.items())))
    csv_file('events_per_second.csv', ['trace_second', 'event', 'count'],
             ((*key, count) for key, count in sorted(bins.items())))
    csv_file('latency_summary.csv', ['tid', 'metric', 'count', 'mean_ns', 'min_ns', 'max_ns'],
             ((tid, metric, row['count'], row['sum_ns'] / row['count'], row['min_ns'], row['max_ns'])
              for (tid, metric), row in sorted(stats.items())))
    summary = {
        'source': str(source), 'source_kind': source_kind, 'vcpu_tids': sorted(tids),
        'diagnostic_files': [str(p) for p in diagnostics],
        'vcpu_ids_by_tid': {str(k): sorted(v) for k, v in sorted(vcpu_ids.items())},
        'first_timestamp_ns': first, 'last_timestamp_ns': last, 'observed_span_seconds': span_s,
        'event_counts': dict(sorted(counts.items())),
        'warnings': {name: count for name, count in sorted(warnings.items()) if count},
        'timing_degraded': any(warnings[key] for key in ('lost_event_markers', 'external_lost_event_markers', 'out_of_order_events',
                                                       'unparsed_target_lines', 'malformed_sched_events')),
        'notes': [
            'Synthetic input remains synthetic; this analyzer cannot establish provenance.',
            'Entry/exit intervals are wall time, not pure guest CPU time or pure exit handling cost.',
            'Scheduler latencies require a synchronized cross-CPU trace clock and both scheduler events.',
            'Rates use first/last relevant events, not requested recording duration.',
            'One-second bins are sparse; missing rows mean zero; first/last bins may be partial.',
            'Loss reported only on stderr/collection.log must also be reviewed by the operator.',
        ],
    }
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'report.md').write_text(
        '# KVM trace analysis\n\n'
        f'- Source kind (caller-supplied): {source_kind}\n- Observed span: {span_s:.9f} s\n- vCPU TIDs: {sorted(tids)}\n'
        f'- Event count: {sum(counts.values())}\n- Timing degraded: {summary["timing_degraded"]}\n'
        f'- Warnings: {summary["warnings"]}\n\n'
        + '\n'.join('- ' + note for note in summary['notes']) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='new output directory')
    parser.add_argument('--tid', type=int, action='append', help='repeat to select vCPU Linux TIDs')
    parser.add_argument('--source-kind', choices=['unspecified', 'synthetic', 'real-kvm', 'real-kvm-microbench'], default='unspecified')
    parser.add_argument('--diagnostics', type=Path, action='append', default=[], help='also inspect collector/report logs for event loss')
    args = parser.parse_args()
    try:
        result = analyze(args.trace, args.out, set(args.tid) if args.tid else None,
                         source_kind=args.source_kind, diagnostics=args.diagnostics)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'error: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
