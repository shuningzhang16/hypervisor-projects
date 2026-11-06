# 第二阶段交付：真实 KVM 观测与 VirtIO 软件验证

这是第二阶段的历史记录。文中当时未完成的 Linux Guest workload、packed ring、热插拔和持续队列测试已在 [第三阶段](PHASE3_REPORT.md) 继续处理。

完成日期：2026-11-05。按用户范围，本轮没有开发或加载自定义 Guest/实体设备驱动。

## 已完成与实际证据

| 项目 | 实际执行结果 | 入口 |
|---|---|---|
| KVM 实验矩阵 | CPU+PIO、PIO、MMIO × 1/2/4 vCPU × 3 次重复 × tracing 开/关，共 54 次通过 | [实验报告](evidence/phase2/kvm-report/report.md) |
| 内核观测 | 27 次录制共 104,790 个 kvm_exit；entry/exit、PIO/MMIO、sched_switch/wakeup 数据已保存 | [汇总](evidence/phase2/kvm-report/summary.json)、[每次运行 CSV](evidence/phase2/kvm-report/runs.csv) |
| 数据完整性 | 所有最终录制均未检测到 lost-event、时间倒序或目标行解析异常；保留了 trace.dat 和诊断日志 | [实验原始目录](evidence/phase2/matrix) |
| 调度延迟 | 按运行、TID、metric 输出精确 nearest-rank P50/P95/P99，未混合不同实验的分位数 | [延迟 CSV](evidence/phase2/kvm-report/latencies.csv) |
| 采集器隔离 | 普通进程实测启动同步、WSL TID 映射和 scheduler 捕获；顶层 tracing 配置前后相同 | [检查日志](evidence/phase2/collector-live-3-console.log)、[配置记录](evidence/phase2/collector-live-3/tracefs-state.json) |
| VirtIO 队列压力 | 65,568 个批量请求、1 次 16-bit index 回绕、128 次 reset；每个响应内容/used length/尾部哨兵均检查 | [测试摘要](evidence/phase2/qtest-stress-final/summary.json) |
| VirtIO 异常与通知 | descriptor 环、越界 next、方向错误、间接描述符、错误间接表长度、通知抑制、未通知请求 reset 清理通过 | [测试日志](evidence/phase2/qtest-stress-final-console.log) |
| QMP 生命周期 | system_reset 后重新协商并正常处理请求；迁移被现有 unmigratable 属性拒绝；正常 quit | [QMP 记录](evidence/phase2/qmp-lifecycle/qmp.jsonl) |
| 离线验证 | 14 个 Python 测试通过；C 协议 10,000 个变长 payload 回环通过 ASan/UBSan；KVM workload 严格编译通过 | [离线日志](evidence/phase2/offline-final/tests.log) |
| 可复现工具 | 新增用户态 workload、实验执行器、报告汇总器、VirtIO trace 分析器、Makefile、独立构建脚本和 CI 配置 | [运行指南](REPRODUCE.md) |

## 测量边界

KVM 数据来自 **WSL2 嵌套 KVM 上的微型 16-bit Guest 程序**，而不是 Linux Guest 的磁盘/网络业务测试。每次用户态退出后主动睡眠 1000 µs，目的是产生可控退出与调度事件并限制采集量；吞吐明显受睡眠与宿主调度影响。实验按固定顺序执行、单次运行两秒，不能把组间差异直接解释为 tracing 的因果性能损失。

VirtIO 压力测试使用暂停 vCPU 的 TCG QEMU，由 qtest 操作模拟 Guest 内存和 PCI/MMIO。它验证设备模型和 ring 行为，没有运行 Guest 内核驱动或中断处理器。`notify_to_complete_ns` 受批处理和开启的 trace 写文件影响；本次日志在 Windows 挂载卷上，不能将这些延迟用作设备或 KVM 性能宣传。[原始完成 CSV 与统计](evidence/phase2/virtio-trace-report/summary.json)

未宣称完成：Linux Guest CPU/磁盘/网络 workload 的端到端实验、自定义 Guest 驱动、真实 VFIO/IOMMU 直通、长时间生产压力、热插拔和 packed ring 验证。迁移仍明确不支持，未放宽既有安全行为。CI 文件已提供，但未推送仓库或执行云端 Actions。

## 本轮发现并处理的问题

1. Ubuntu 的 trace-cmd 2.9.6 对 `--version` 输出版本后返回 1。采集器现在识别有效版本输出，真正 record 失败仍正常报错；依赖只下载/解包到独立目录，未做系统安装。
2. 首次微型 KVM workload 成功产生 1,594 个用户态 PIO 退出，但 trace 为空。最初怀疑启动时序；同步启动后的普通进程对照仍为空，最终确认 WSL 的外层 tracepoint TID 与 `/proc` TID 不同。现用每个协作线程写入专属 trace_marker 实例的方法获得精确映射，例如本地 615→内核 979，再按真实 TID 过滤。普通 Linux 原生 PID 场景仍可直接 `--pid`；嵌套 PID namespace 下普通 QEMU 采集需明确提供外层 `--trace-tids`，本工具没有虚构自动映射能力。
3. 新增的“未映射 GPA 必须 NEEDS_RESET”测试预期不符合 QEMU 9.2 的 bounce-buffer 行为。实际设备返回空 BAD_REQUEST；现测试严格检查错误状态、16 字节 used length 和未写越界/额外 payload。原 descriptor 安全检查和设备代码没有放宽。失败日志保留在 [第一次压力测试](evidence/phase2/qtest-stress-console.log)。
4. 对全部 27 份原始 trace 做离线最终重分析，额外检查 collection.log/report.stderr 中的丢事件标记，输出 `analysis-final`；没有为报告重做 KVM 测量。

旧阶段的原始证据完整保留；主源码仍以 QEMU 9.2.0 为目标，既有设备补丁没有因新增测试而改变。
