# KVM VM Exit Tracing & Performance Analyzer

2026-11-05：已完成微型 KVM 实验及真实 Linux Guest CPU/磁盘/网络 48 次对比。普通 QEMU 在嵌套 PID namespace 中的 TID 由配套 `perf_tid_map.c` 精确映射，正式采集仍传外层 `--trace-tids`。入口为 `run_linux_matrix.py`、`summarize_linux_matrix.py`，结果见 [性能报告](../PERFORMANCE_REPORT.md)，复现见 [根目录指南](../REPRODUCE.md)。

## 环境

普通 x86-64 Linux PC、硬件虚拟化启用、可读写 `/dev/kvm`、可读 tracefs、Python 3.10+ 和 trace-cmd。检查脚本不安装依赖、不加载内核模块、不挂载文件系统，也不创建 VM。

```bash
bash check_host.sh
# Ubuntu/Debian 上按需安装：
sudo apt install qemu-system-x86 trace-cmd python3 stress-ng fio iperf3
```

若 tracefs 未挂载，先检查 `findmnt -t tracefs` 与内核配置，再由系统管理员挂载。若 KVM 无权限，配置当前用户的 kvm 组访问并重新登录。仅存在 `/dev/kvm` 并不能证明 Guest 已经使用 KVM。

## 启动自己的 Linux Guest

以下从项目根目录执行；`guest.qcow2` 是你已安装好 Linux 的 qcow2 镜像。`-snapshot` 使此示例的磁盘修改不写回原镜像；Guest 中应已有 SSH 和 workload 工具。

```bash
mkdir -p runs
qemu-system-x86_64 -enable-kvm -cpu host -smp 2 -m 2048 \
  -drive file=/path/to/guest.qcow2,format=qcow2,if=virtio,snapshot=on \
  -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:55201-:5201 \
  -pidfile runs/qemu.pid
```

若 KVM 加速无法初始化，上述命令应失败，不改用 TCG 来填充 KVM 性能结果。SSH 登录后在 Guest 内独立运行 workload：

```bash
# CPU：
stress-ng --cpu 2 --timeout 60s --metrics-brief
# 磁盘：只写 Guest 内的专用普通文件，不对块设备执行。
mkdir -p "$HOME/virtio-lab-data"
fio --name=lab --filename="$HOME/virtio-lab-data/fio-test.bin" \
    --size=256M --rw=randrw --bs=4k --iodepth=16 --ioengine=libaio \
    --direct=1 --time_based --runtime=60 --group_reporting
# 网络：Guest 启动一次服务，Host 执行下一条 client 命令。
iperf3 -s -1
```

Host 网络命令为 `iperf3 -c 127.0.0.1 -p 55201 -t 60`。user-mode networking 本身有开销；此实验观察整体路径，不能用来宣称裸 VirtIO 网卡吞吐。

## 采集与分析

workload 运行并预热后，在 Host 的另一个终端：

```bash
sudo bash kvm_exit_analyzer/collect_kvm_trace.sh \
  --pid "$(cat runs/qemu.pid)" --seconds 30 --output runs/cpu-01
python3 kvm_exit_analyzer/analyze_trace.py runs/cpu-01/trace.txt \
  --out runs/cpu-01-analysis
```

采集使用独立 trace instance，过滤 QEMU 进程已有线程。KVM 事件过滤 `common_pid`；scheduler 过滤 `prev_pid/next_pid` 或被唤醒 `pid`，不能用发出 wakeup 的线程 PID 代替目标 TID。默认不采集其他进程的完整 scheduler 流。采集期间不要增加 vCPU；新线程不在开始时取得的过滤集合内。

`kvm_entry/kvm_exit` 为必需事件；MMIO/PIO 和 scheduler 按本机可用性选择。`--no-sched` 可降低采集量。每 CPU trace buffer 为 4096 KiB，事件过滤限制了输出量，仍需检查丢事件。脚本执行正常结束或失败均保留已有原始文件和日志；遇到中断也先保留文件，不自动重跑。

`trace-cmd report -N -t` 输出禁用可选解码插件并保留纳秒。分析器接受带/不带 subsystem 前缀和常见 ftrace flag 的文本。不同内核/trace-cmd 的新格式可能需要增加测试并调整解析；未识别的目标行会被计入 warning。

手动重新导出已有 trace：

```bash
trace-cmd report -N -t -i runs/cpu-01/trace.dat > runs/cpu-01/trace.txt
```

## 输出解释

| 文件 | 含义 |
|---|---|
| event_counts.csv | 按事件计数；每秒频次使用首末相关事件跨度 |
| exit_reasons.csv | 按 Linux TID、ISA 和原始原因统计；不猜测 numeric code |
| events_per_second.csv | 以 trace clock 的整秒分桶；稀疏输出，缺失行计 0，首末桶可能不完整 |
| intervals.csv | 每个有效配对的结束时间、TID、类别和纳秒间隔 |
| latency_summary.csv | 按 TID/类别计算样本量、均值、最小值、最大值 |
| summary.json / report.md | 可读摘要、warnings、证据局限 |

四类间隔：

- `entry_to_exit_wall`：进入到退出 guest 的墙钟间隔，含期间可能发生的 host 中断或调度影响。
- `exit_to_entry_wall`：退出后到再次进入的墙钟间隔，含内核/QEMU 处理、阻塞和调度；不是纯 VM Exit 开销。
- `wakeup_to_run`：`sched_wakeup` 到目标 TID 第一次被切入。
- `preempt_to_run`：目标以 runnable 状态切出到下一次切入；睡眠时间不计入这个指标。

按 TID 配对，不把不同 QEMU 进程里相同 vCPU ID 合并。`--tid 123 --tid 124` 可显式选择。丢事件、时间倒序或目标行解析失败会清除未完成配对并标记降级，不跨缺口计算时间。采集开始/结束产生未配对事件是正常的截断现象。

分析器需要可再次读取的文件，以两遍扫描识别 vCPU。详细 interval 流式写出，内存使用随 TID 和事件时间桶数量增长。配套汇总器从 interval CSV 按实验/TID/metric 分组计算精确分位数，一次只加载一份运行的间隔。

## 真实采集前尚需验证

当前已验证 trace-cmd 2.9.6、WSL kernel 6.6.114.1 上的微型采集和配套 Linux Guest workload。没有宣称覆盖所有内核、业务负载或原生物理主机。`--diagnostics` 可将 `collection.log`、`report.stderr` 纳入丢事件检查；目标 Host 的新版本和追踪扰动仍应实测。
