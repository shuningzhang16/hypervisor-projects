#!/usr/bin/env python3
"""Summarize completed run_experiments results. Exact quantiles, one run in memory."""
import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def nearest_rank(sorted_values, percent):
    if not sorted_values:
        return None
    return sorted_values[max(0, math.ceil(percent / 100 * len(sorted_values)) - 1)]


def summarize(root, output):
    output.mkdir(parents=True, exist_ok=False)
    rows, latency_rows = [], []
    groups = defaultdict(list)
    reasons = Counter()
    for result_path in sorted(root.glob('*/result.json')):
        result = json.loads(result_path.read_text())
        directory = result_path.parent
        workers = result['workload']['workers']
        active = max(w['elapsed_ns'] for w in workers) / 1e9
        io_count = sum(w['io_exits'] for w in workers)
        mmio_count = sum(w['mmio_exits'] for w in workers)
        rate = (io_count + mmio_count) / active if active else 0
        analysis_dir = directory / ('analysis-final' if (directory / 'analysis-final').exists() else 'analysis')
        summary_path = analysis_dir / 'summary.json'
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else None
        row = {'run': directory.name, 'mode': result['mode'], 'vcpus': result['vcpus'],
               'repeat': result['repeat'], 'tracing': result['tracing'], 'active_seconds': active,
               'userspace_io_exits': io_count, 'userspace_mmio_exits': mmio_count,
               'userspace_exits_per_second': rate,
               'kernel_exit_events': summary['event_counts'].get('kvm_exit', 0) if summary else None,
               'timing_degraded': summary['timing_degraded'] if summary else None}
        rows.append(row)
        groups[(result['mode'], result['vcpus'], result['tracing'])].append(rate)
        if summary:
            intervals = defaultdict(list)
            with (analysis_dir / 'intervals.csv').open() as stream:
                for sample in csv.DictReader(stream):
                    intervals[(int(sample['tid']), sample['metric'])].append(int(sample['duration_ns']))
            for (tid, metric), values in sorted(intervals.items()):
                values.sort()
                latency_rows.append({'run': directory.name, 'tid': tid, 'metric': metric, 'count': len(values),
                                     'mean_ns': statistics.fmean(values), 'p50_ns': nearest_rank(values, 50),
                                     'p95_ns': nearest_rank(values, 95), 'p99_ns': nearest_rank(values, 99),
                                     'max_ns': values[-1], 'timing_degraded': summary['timing_degraded']})
            with (analysis_dir / 'exit_reasons.csv').open() as stream:
                for reason in csv.DictReader(stream):
                    reasons[(result['mode'], result['vcpus'], reason['isa'], reason['reason'])] += int(reason['count'])
    if not rows:
        raise ValueError('no completed experiment results found')
    def write_csv(name, data, fields):
        with (output / name).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
    write_csv('runs.csv', rows, list(rows[0]))
    latency_fields = ['run', 'tid', 'metric', 'count', 'mean_ns', 'p50_ns', 'p95_ns', 'p99_ns', 'max_ns', 'timing_degraded']
    write_csv('latencies.csv', latency_rows, latency_fields)
    grouped = [{'mode': mode, 'vcpus': vcpus, 'tracing': tracing, 'repeats': len(values),
                'mean_exits_per_second': statistics.fmean(values), 'min_exits_per_second': min(values),
                'max_exits_per_second': max(values)} for (mode, vcpus, tracing), values in sorted(groups.items())]
    write_csv('groups.csv', grouped, list(grouped[0]))
    reason_rows = [dict(zip(['mode', 'vcpus', 'isa', 'reason', 'count'], (*key, value))) for key, value in sorted(reasons.items())]
    write_csv('reasons.csv', reason_rows, ['mode', 'vcpus', 'isa', 'reason', 'count'])
    failures = [str(p.relative_to(root)) for p in sorted(root.glob('*/failure.txt'))]
    degraded = [row['run'] for row in rows if row['timing_degraded']]
    text = ['# 实际 KVM 微型工作负载实验', '',
            f'完成 {len(rows)} 次运行；记录到失败目录 {len(failures)} 个；时序降级 {len(degraded)} 次。', '',
            '这是 WSL2 嵌套 KVM 上的 16-bit 微型 Guest 程序，没有 Linux Guest 或自定义驱动。',
            '每次用户态退出后主动睡眠 1000 µs，用来验证调度关联并限制采集量；吞吐主要受睡眠和宿主调度影响。',
            '以下结果不能解释为硬件极限、Linux CPU/磁盘/网络 workload 性能或纯 VM Exit 成本。', '',
            '| 模式 | vCPU | tracing | 重复 | 用户态退出/秒均值 | 最小 | 最大 |',
            '|---|---:|---|---:|---:|---:|---:|']
    for row in grouped:
        text.append(f'| {row["mode"]} | {row["vcpus"]} | {row["tracing"]} | {row["repeats"]} | '
                    f'{row["mean_exits_per_second"]:.1f} | {row["min_exits_per_second"]:.1f} | {row["max_exits_per_second"]:.1f} |')
    text += ['', '## 数据解释', '',
             '- 用户态退出/秒 = 所有 vCPU 的 IO+MMIO 用户态退出计数 / 最长 worker 实际运行时间；内核 kvm_exit 还包含内核内部处理的其他退出。',
             '- CPU 模式在每次 PIO 前执行 60000 次减计数；PIO 模式连续触发端口访问；MMIO 模式访问 64 KiB RAM 之外的模拟地址。',
             '- `latencies.csv` 按运行、TID、metric 给出样本数与精确 nearest-rank P50/P95/P99；没有跨运行合并分位数。',
             '- 配置按固定顺序执行，且单次仅两秒；tracing 开关组的差异含顺序、调度和系统负载因素，不能直接当成因果开销估计。',
             '- 实验原始证据位于输入目录下的各运行文件夹，包含 trace.dat、trace.txt、线程 ID 映射和完整命令。',
             f'- 失败目录：{failures}；降级运行：{degraded}。', '']
    (output / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    return {'runs': len(rows), 'failures': failures, 'degraded': degraded,
            'kernel_exit_events': sum(row['kernel_exit_events'] or 0 for row in rows)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiments', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.experiments, args.out), indent=2))
