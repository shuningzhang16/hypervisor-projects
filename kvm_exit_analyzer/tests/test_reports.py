import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summarize_experiments import nearest_rank
from trace_tid_map import TraceTidMap


class ReportTests(unittest.TestCase):
    def test_exact_quantiles(self):
        values = list(range(1, 101))
        self.assertEqual([nearest_rank(values, p) for p in (50, 95, 99)], [50, 95, 99])
        self.assertEqual(nearest_rank([5, 10], 95), 10)
        self.assertIsNone(nearest_rank([], 50))

    def test_marker_pid_namespace_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapper = TraceTidMap()
            mapper.path = Path(tmp)
            (mapper.path / 'trace').write_text(
                '# tracer: nop\n'
                ' lab-vcpu-0-900 [002] ..... 10.0: tracing_mark_write: hypervisor_tid=123\n'
                ' lab-vcpu-1-901 [001] ..... 10.1: tracing_mark_write: hypervisor_tid=124\n')
            self.assertEqual(mapper.resolve([123, 124]), {123: 900, 124: 901})
            with self.assertRaisesRegex(RuntimeError, 'missing thread markers'):
                mapper.resolve([125])
