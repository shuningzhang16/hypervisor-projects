#!/usr/bin/env python3
"""Summarize real Linux guest runs without mixing latency samples across runs."""
import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from summarize_experiments import nearest_rank


def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def summarize(root, output):
    output.mkdir(parents=True, exist_ok=False)
    runs, latencies = [], []
    groups, pairs = defaultdict(list), defaultdict(dict)
    reasons, events = Counter(), Counter()
    for path in sorted(root.glob('*/*/result.json')):
        row = json.loads(path.read_text())
        row['run'] = str(path.parent.relative_to(root))
        row.setdefault('kvm_exits', None); row.setdefault('timing_degraded', None)
        row['window_seconds'] = (row['host_end_ns'] - row['host_start_ns']) / 1e9
        runs.append(row)
        key = row['configuration'], row['mode']
        groups[(*key, row['traced'])].append(row['rate'])
        pairs[(*key, row['repeat'])][row['traced']] = row['rate']
        if row['traced']:
            directory = path.parent / 'analysis'
            summary = json.loads((directory / 'summary.json').read_text())
            events.update(summary['event_counts'])
            values = defaultdict(list)
            with (directory / 'intervals.csv').open() as stream:
                for sample in csv.DictReader(stream):
                    values[(sample['tid'], sample['metric'])].append(int(sample['duration_ns']))
            for (tid, metric), samples in sorted(values.items()):
                samples.sort()
                latencies.append({'run': row['run'], 'tid': tid, 'metric': metric, 'count': len(samples),
                                  'p50_ns': nearest_rank(samples, 50), 'p95_ns': nearest_rank(samples, 95),
                                  'p99_ns': nearest_rank(samples, 99), 'max_ns': samples[-1]})
            with (directory / 'exit_reasons.csv').open() as stream:
                for reason in csv.DictReader(stream):
                    reasons[(*key, reason['isa'], reason['reason'])] += int(reason['count'])
    if not runs: raise ValueError('No completed Linux guest runs')
    group_rows = [{'configuration': config, 'mode': mode, 'traced': traced,
                   'n': len(values), 'mean_rate': statistics.fmean(values),
                   'stdev_rate': statistics.stdev(values) if len(values) > 1 else 0,
                   'min_rate': min(values), 'max_rate': max(values)}
                  for (config, mode, traced), values in sorted(groups.items())]
    pair_rows = [{'configuration': config, 'mode': mode, 'repeat': repeat,
                 'trace_off_rate': values[False], 'trace_on_rate': values[True],
                 'on_vs_off_percent': 100 * (values[True] / values[False] - 1)}
                for (config, mode, repeat), values in sorted(pairs.items())
                if set(values) == {False, True}]
    reason_rows = [dict(zip(['configuration', 'mode', 'isa', 'reason', 'count'], (*key, value)))
                   for key, value in sorted(reasons.items())]
    write_csv(output / 'runs.csv', runs, list(runs[0]))
    write_csv(output / 'groups.csv', group_rows, list(group_rows[0]))
    write_csv(output / 'paired.csv', pair_rows,
              ['configuration', 'mode', 'repeat', 'trace_off_rate', 'trace_on_rate', 'on_vs_off_percent'])
    write_csv(output / 'latencies.csv', latencies,
              ['run', 'tid', 'metric', 'count', 'p50_ns', 'p95_ns', 'p99_ns', 'max_ns'])
    write_csv(output / 'exit_reasons.csv', reason_rows, ['configuration', 'mode', 'isa', 'reason', 'count'])
    metadata = json.loads((root / 'experiment.json').read_text())
    expected = sum(len(config[-1]) for config in metadata['configurations']) * (1 if metadata.get('smoke') else metadata['repeats'] * 2)
    result = {'completed_runs': len(runs), 'expected_runs': expected, 'paired_runs': len(pair_rows),
              'traced_runs': sum(row['traced'] for row in runs), 'event_counts': dict(events),
              'degraded_runs': [row['run'] for row in runs if row['timing_degraded']],
              'source': 'real Linux Guest on WSL2 nested KVM'}
    (output / 'summary.json').write_text(json.dumps(result, indent=2))
    text = ['# Linux Guest 实验结果', '',
            f'完成 {len(runs)}/{expected} 次运行、{len(pair_rows)} 对 tracing 开关对照；'
            f'工作负载窗口内共 {events["kvm_exit"]:,} 个 kvm_exit。', '',
            'QEMU 9.2.0；WSL2 嵌套 KVM；Guest 使用本机 Linux 6.6.114.1 内核与标准驱动。',
            f'每个配置先预热 1 秒，每次测量 {metadata["seconds"]} 秒、计划重复 {metadata["repeats"]} 次，逐次交替 tracing 开关顺序。',
            '未绑定 CPU；宿主 Windows/WSL 后台负载与调频未隔离。以下是本环境的短时观测，不是设备额定性能。', '',
            '| 配置 | 工作负载 | tracing | 次数 | 平均速率 | 最小 | 最大 |',
            '|---|---|---|---:|---:|---:|---:|']
    for row in group_rows:
        scale, unit = (1e6, 'Miter/s') if row['mode'] == 'cpu' else (1048576, 'MiB/s')
        text.append(f'| {row["configuration"]} | {row["mode"]} | {row["traced"]} | {row["n"]} | '
                    f'{row["mean_rate"]/scale:.3f} {unit} | {row["min_rate"]/scale:.3f} | {row["max_rate"]/scale:.3f} |')
    text += ['', '## 指标含义', '',
             '- CPU：每个 vCPU 对应一个普通 pthread，计算整数循环的总 iterations/s；没有自定义驱动。',
             '- 磁盘：64 KiB O_DIRECT 写入→fdatasync→读回校验，循环使用 32 MiB 文件。速率只计已验证写入字节；不等于纯读/写带宽或物理 SSD 性能。',
             '- 网络：单 TCP 连接串行 64 KiB echo，逐块验证。只计单向有效载荷；包含 Guest TCP、QEMU user-net/slirp、WSL loopback server 与往返延迟，不是网卡极限。',
             '- 原始完整 trace.dat/trace.txt 保留在各 run/trace 中；分析窗口为宿主 CLOCK_MONOTONIC 下命令发送至结果接收，包含串口控制开销。',
             '- P50/P95/P99 在 latencies.csv 按运行/TID/metric 分开计算；entry→exit、exit→entry 都是墙钟间隔，含调度等开销。',
             '- common_pid 使用绑定特定本地 TID 的短期 perf tracepoint 采样取得；映射在启动阶段结束，正式测量期间没有该采样器。',
             '- 256/512 MiB 对照使用相同小工作集 CPU 程序；没有压力到内存容量，不能推导内存容量的普遍收益。', '',
             '## Tracing 开关对照', '',
             'paired.csv 保存每次成对速率差：100 × (开启/关闭 − 1)。正值表示该次开启组更快。',
             '短时样本数量有限、配置固定顺序与未隔离宿主，差异含调频/缓存/调度噪声，不能直接认定是 tracing 的因果损耗。', '',
             '| 配置 | 工作负载 | 成对差均值 | 最小 | 最大 |',
             '|---|---|---:|---:|---:|']
    differences = defaultdict(list)
    for row in pair_rows:
        differences[(row['configuration'], row['mode'])].append(row['on_vs_off_percent'])
    for (config, mode), values in sorted(differences.items()):
        text.append(f'| {config} | {mode} | {statistics.fmean(values):+.2f}% | {min(values):+.2f}% | {max(values):+.2f}% |')
    text += ['', f'时序降级运行：{result["degraded_runs"]}。采集开始/结束造成的不完整配对保留在每次 summary.json 中。', '']
    (output / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrix', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.matrix, args.out), indent=2))
