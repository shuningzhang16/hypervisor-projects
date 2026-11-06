# 第三阶段：Linux Guest 实验与设备可靠性验证

2026-11-06 后续更新：下文记录第三阶段当时的范围；此前缺少的 Guest 功能驱动交互现已完成，见 [Guest 驱动验证报告](GUEST_DRIVER_REPORT.md)。

日期：2026-11-05。此报告记录第三阶段实际完成的代码与实验，不是全部目标已完成的声明。此前助手将“除了真实驱动”解释为也排除 Guest 功能驱动；用户并未分别明确两类驱动。真实 Guest 功能交互目前未完成，整体状态以 [全部要求核对](ALL_REQUIREMENTS_AUDIT.md) 为准。

## 完成证据

| 项目 | 实际结果 | 证据 |
|---|---|---|
| 真正 Linux Guest workload | CPU、磁盘、TCP echo；48/48 次成功，24 对 tracing 开关实验 | [运行摘要](evidence/phase3/linux-report/summary.json)、[全部 CSV](evidence/phase3/linux-report/runs.csv) |
| 配置对照 | 1/2/4 vCPU、256/512 MiB、virtio-blk/AHCI、virtio-net/e1000；各 3 次重复 | [性能报告](PERFORMANCE_REPORT.md) |
| KVM 事件 | 工作窗口内 181,585 个 exit；entry/exit、MMIO/PIO、scheduler 事件均采到 | [计数](evidence/phase3/linux-report/summary.json)、[原始 24 份录制](evidence/phase3/linux-matrix) |
| 调度与退出分析 | 按运行/TID/metric 的精确 P50/P95/P99；未检测到时序降级 | [分位数](evidence/phase3/linux-report/latencies.csv)、[退出原因](evidence/phase3/linux-report/exit_reasons.csv) |
| 普通 QEMU / WSL TID 映射 | perf_event_open 精确绑定本地 TID，读取 common_pid；测量前关闭采样器 | [首次映射证据](evidence/phase3/boot-first/tid-map.json)、[实现](kvm_exit_analyzer/workloads/perf_tid_map.c) |
| Packed ring | 4,096 次请求、1,081 次 wrap 切换、32 次 reset；SG 跨界、通知抑制、错误恢复通过 | [摘要](evidence/phase3/packed/summary.json) |
| PCIe 热插拔 | 真正 Linux Guest 中 32 次添加/移除；sysfs 枚举、QMP DEVICE_DELETED 和最后 CPU workload 均成功 | [摘要](evidence/phase3/hotplug/summary.json)、[逐次记录](evidence/phase3/hotplug/cycles.json) |
| 持续队列测试 | 同一 QEMU 进程运行 611.859 秒；1,049,088 个批量请求、512 次 reset、16 次 index 回绕；16 轮 RSS 均为 34,004 KiB | [摘要](evidence/phase3/soak/summary.json)、[逐轮记录](evidence/phase3/soak/rounds.jsonl) |
| 本地回归 | 14 个 Python 测试；10,000 个 C payload ASan/UBSan 检查；三个用户态 C 程序严格编译通过 | [日志](evidence/phase3/offline/tests.log) |
| 可复现交付 | 源码、QEMU 9.2.0 patch、Linux Guest 资产、脚本、CSV、原始 trace 和使用说明 | [复现指南](REPRODUCE.md)；Guest 资产包位于桌面本地 `artifacts/linux-guest.tar.gz`，GitHub 存放范围见 [证据说明](evidence/README.md) |

之前的完整 QEMU 构建与修复证据保留在 [第一阶段验证](VALIDATION.md)；54 次微型 KVM 实验、split ring 回绕与 QMP 迁移拒绝保留在 [第二阶段报告](PHASE2_REPORT.md)。本轮设备 C 代码没有改变，新增验证针对已编译的同一实现。

## 本轮具体补充

1. 用现成 WSL 内核、静态 BusyBox 和标准模块构建小型 initramfs，启动真正的 Linux Guest。新增的 C workload 是普通用户态程序，不是驱动。
2. 解决普通 QEMU 在 WSL PID namespace 下的 trace 线程映射；无需协作式 QEMU 修改、全系统 scheduler 录制或 PID 猜测。
3. 使用 trace-cmd 启用后的 ready 通知，再通过串口执行 Guest workload；保存完整录制，并单独分析宿主 monotonic 工作窗口。
4. 将原“报告模板”更新为实际结论，空白模板保留在 docs；性能差异与测量限制一起呈现。
5. 增加 packed ring、标准 PCIe 热插拔和有时限的同进程队列压力，复用现有队列校验，没有放宽错误处理、reset 或迁移限制。

## 哪些没有做、为什么

- **自定义 Guest/真实硬件驱动：** 用户说“除了真实驱动”；此前助手把 Guest 功能驱动也一并排除了，这一解释尚需明确。实际 virtio-lab 功能请求由 qtest 提交；Guest 热插拔使用已有 PCIe/virtio-pci transport，设备未绑定自定义功能驱动。
- **VFIO/IOMMU 物理直通：** 没有真实 PCI 设备，不在本次软件实验范围。
- **生产级完整 Hypervisor：** 本项目是 KVM 观测工具与 QEMU 设备模型。十分钟软件压力和 RSS 观察不等于长期泄漏证明、恶意 Guest 全面安全审计或生产认证；QEMU 主程序没有在本轮整体启用 sanitizer，协议 C 测试启用了 ASan/UBSan。
- **迁移：** 保持显式不支持，已有拒绝测试；没有新增迁移格式或放宽现有保护。
- **云端 CI / 发布：** 配置已提供，本地验证已执行；未推送远程仓库、运行云端 Actions 或部署。

KVM 性能结果限定于本机 WSL2 嵌套虚拟化与三秒短测；TCG/qtest 结果只用于设备功能和持续运行验证。详细边界见 [性能报告](PERFORMANCE_REPORT.md)。
