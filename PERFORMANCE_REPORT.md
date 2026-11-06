# Linux Guest 性能观测报告

日期：2026-11-05。48 次真实 Linux Guest 运行全部完成；24 次启用 KVM/scheduler tracing，24 次关闭。每组 3 次、单次 3 秒、预热 1 秒，重复间交替 tracing 开关顺序。原始结果与完整表格见 [自动生成报告](evidence/phase3/linux-report/report.md)、[每次运行](evidence/phase3/linux-report/runs.csv)、[成对差值](evidence/phase3/linux-report/paired.csv)。

## 主要观察

| 对照 | 关闭 tracing 的平均观测值 | 可以支持的结论 |
|---|---|---|
| CPU：1 / 2 / 4 vCPU，256 MiB | 353.771 / 668.667 / 1326.533 Miter/s | 本整数循环在当前环境中扩展到 4 vCPU；约为单 vCPU 的 3.75 倍 |
| CPU：2 vCPU，256 / 512 MiB | 668.667 / 638.625 Miter/s | 小工作集未耗尽内存；3 次短测不能推断增大内存会变慢 |
| 磁盘：virtio-blk / AHCI | 4.869 / 5.501 MiB/s | 这是写→同步→读回校验的整体速率；AHCI 样本区间很宽，不能据均值断言它更快 |
| 网络：virtio-net / e1000 | 1.687 / 1.570 MiB/s | 这是单连接 64 KiB 串行 echo 路径，包含 SLIRP 和往返延迟；不代表网卡带宽 |

全部工作负载窗口记录到 **181,585 次 kvm_exit、57,608 次 MMIO、6,286 次 PIO、36,387 次 sched_switch、18,159 次 sched_wakeup**。没有检测到丢事件、目标行解析异常或时间倒序导致的时序降级。[计数摘要](evidence/phase3/linux-report/summary.json)

各运行/TID 的 entry→exit、exit→entry、wakeup→run、preempt→run 分布见 [分位数 CSV](evidence/phase3/linux-report/latencies.csv)。退出原因保持内核给出的 ISA/原因名称，见 [退出原因 CSV](evidence/phase3/linux-report/exit_reasons.csv)。墙钟间隔不能直接命名为纯 KVM exit 成本。

## 环境与方法

- Host：Windows + WSL2，AMD Ryzen 7 5800H，WSL Linux 6.6.114.1；Guest 使用同版本的现成内核和标准模块。
- QEMU：已集成实验设备的 9.2.0，KVM 加速，CPU host；所有 QEMU 启动参数和 boot serial 日志在 [矩阵目录](evidence/phase3/linux-matrix)。未绑定 CPU、未隔离宿主后台进程。
- 磁盘：每台 VM 使用新复制的 192 MiB ext4 虚拟磁盘；Guest 写 32 MiB 循环文件，64 KiB O_DIRECT，每块 fdatasync 后读回核对。
- 网络：Guest → 10.0.2.2 → WSL 127.0.0.1 echo 服务，仅本机测试；没有外网吞吐测试。
- 普通 QEMU 的 PID namespace 映射通过 `perf_event_open` 绑定每个本地 vCPU TID，并读取对应 tracepoint 的 common_pid；只在启动阶段采样，测量开始前已关闭。
- trace-cmd 使用独立 trace instance、mono clock 和准确 TID 过滤；正式窗口为宿主发送工作命令至收到完成结果。Guest 速率使用 Guest 自己的 CLOCK_MONOTONIC；二者均记录，不能假定两个时钟完全一致。
- 完整 trace.dat/trace.txt 保留；裁剪后的 workload-trace.txt 只用于明确的工作窗口，未知行和丢事件标记仍保留。

## 局限与使用方式

这是短时、嵌套虚拟化环境内的可复现实验。开启 tracing 的组有时更快、有时更慢，反映缓存、调频、调度和测量噪声；当前数据不能得出 tracing 因果开销的可靠百分比。磁盘在 Guest 页缓存之外执行 I/O，仍经过 QEMU、WSL 虚拟磁盘和 Windows 存储层。

设备模型压力测试另用 TCG/qtest 验证功能，没有用其耗时替代 KVM 性能。扩展为生产评估时需要目标原生 Linux 主机、更长时间、多次独立会话以及明确业务负载；这些属于新的部署环境验证。

原始空白报告模板保留在 [模板](docs/PERFORMANCE_REPORT_TEMPLATE.md)。
