import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('analyze_trace', ROOT / 'analyze_trace.py')
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def event(t, name, body, tid=101, cpu=1):
    return f' CPU 0/KVM-{tid} [{cpu:03d}] d..2 {t}: {name}: {body}\n'


class AnalyzerTests(unittest.TestCase):
    def run_trace(self, text, tids=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'trace.txt'
        source.write_text(text, encoding='utf-8')
        summary = mod.analyze(source, root / 'out', tids)
        with (root / 'out' / 'intervals.csv').open() as f:
            rows = list(csv.DictReader(f))
        return summary, rows

    def test_fixture_intervals_and_scheduler(self):
        summary, rows = self.run_trace((ROOT / 'tests/fixtures/synthetic_trace.txt').read_text())
        self.assertEqual(summary['event_counts']['kvm_exit'], 3)
        self.assertEqual(summary['observed_span_seconds'], 1)
        self.assertFalse(summary['timing_degraded'])
        grouped = {}
        for row in rows:
            grouped.setdefault(row['metric'], []).append(int(row['duration_ns']))
        self.assertEqual(grouped['wakeup_to_run'], [200000])
        self.assertEqual(grouped['preempt_to_run'], [500000])
        self.assertEqual(grouped['exit_to_entry_wall'], [1000000, 200000])
        self.assertEqual(grouped['entry_to_exit_wall'], [1000000, 1000000, 996500000])

    def test_loss_breaks_pairs(self):
        summary, rows = self.run_trace(event('1.0', 'kvm_entry', 'vcpu 0') +
                                       'CPU: 1 [LOST 8 EVENTS]\n' +
                                       event('1.1', 'kvm_exit', 'reason HLT'))
        self.assertEqual(rows, [])
        self.assertTrue(summary['timing_degraded'])

    def test_no_pair_between_tids(self):
        _, rows = self.run_trace(event('1.0', 'kvm_entry', 'vcpu 0') +
                                 event('1.1', 'kvm_exit', 'reason NPF', tid=102))
        self.assertEqual(rows, [])

    def test_timestamp_precision_namespace_and_spaces(self):
        parsed = mod.parse_line(' CPU 0/KVM-101 [001] 123456789.123456789: kvm:kvm_exit: reason=48 isa=1')
        self.assertEqual(parsed.ns, 123456789123456789)
        self.assertEqual(mod.exit_reason(parsed.body), '48')

    def test_wakeup_target_not_emitter_and_first_wake(self):
        _, rows = self.run_trace(event('1.0', 'sched_wakeup', 'comm=CPU 0/KVM pid=101', tid=77) +
                                 event('1.1', 'sched_wakeup', 'comm=CPU 0/KVM pid=101', tid=77) +
                                 event('1.2', 'sched_switch', 'prev_pid=77 prev_state=S next_pid=101', tid=77), {101})
        self.assertEqual(int(rows[0]['duration_ns']), 200000000)

    def test_backward_clock_clears_pairs(self):
        summary, rows = self.run_trace(event('2.0', 'kvm_entry', 'vcpu 0') +
                                       event('1.0', 'kvm_exit', 'reason HLT'))
        self.assertTrue(summary['timing_degraded'])
        self.assertEqual(rows, [])

    def test_single_timestamp_has_no_infinite_rate(self):
        summary, _ = self.run_trace(event('1.0', 'kvm_entry', 'vcpu 0'))
        self.assertEqual(summary['observed_span_seconds'], 0)

    def test_malformed_event_marks_degraded(self):
        summary, rows = self.run_trace(event('1.0', 'kvm_entry', 'vcpu 0') +
                                       'new unexpected kvm_exit: format\n' +
                                       event('1.1', 'kvm_exit', 'reason HLT'))
        self.assertTrue(summary['timing_degraded'])
        self.assertEqual(rows, [])

    def test_sleep_is_not_runqueue_delay(self):
        _, rows = self.run_trace(event('1.0', 'sched_switch', 'prev_pid=101 prev_state=S next_pid=77') +
                                 event('2.0', 'sched_switch', 'prev_pid=77 prev_state=S next_pid=101'), {101})
        self.assertEqual(rows, [])

    def test_empty_trace_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No vCPU'):
            self.run_trace('cpus=4\n')

    def test_real_instance_prefix(self):
        row = mod.parse_line('kvm-lab-616: lab-vcpu-0-979 [008] 15.945896863: kvm_entry: vcpu 0, rip 0x1000')
        self.assertEqual((row.tid, row.ns, row.name), (979, 15945896863, 'kvm_entry'))

    def test_external_loss_marks_timing_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'trace.txt'
            source.write_text(event('1.0', 'kvm_entry', 'vcpu 0') + event('1.1', 'kvm_exit', 'reason HLT'))
            diagnostic = root / 'report.stderr'
            diagnostic.write_text('CPU 1: 7 EVENTS LOST\n')
            result = mod.analyze(source, root / 'out', source_kind='synthetic', diagnostics=[diagnostic])
            self.assertTrue(result['timing_degraded'])
            self.assertEqual(result['warnings']['external_lost_event_markers'], 1)
            self.assertEqual(result['source_kind'], 'synthetic')


if __name__ == '__main__':
    unittest.main()
