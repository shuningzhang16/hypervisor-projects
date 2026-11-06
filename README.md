# KVM 观测与 QEMU VirtIO 设备实验工程

本目录包含可运行的 KVM trace 分析器、面向 **QEMU v9.2.0** 的 VirtIO echo 设备，以及已编译并在真实 Linux Guest 中运行验证的功能驱动。2026-11-06 已补齐此前缺少的 Guest 请求/中断/超时/reset/卸载链路，结果见 [Guest 驱动验证](GUEST_DRIVER_REPORT.md)。原始要求的逐项实现和验证范围见 [完整核对表](ALL_REQUIREMENTS_AUDIT.md)；生产部署、迁移和实体硬件验证不在已完成声明中。

2026-11-05 已补完 Linux Guest CPU/磁盘/网络实验：48 次运行、24 份真实 KVM 录制、181,585 个工作负载窗口内的 VM exit。还验证了 packed ring 和 Linux Guest PCIe 热插拔。前期 54 次微型 KVM 实验和 split ring 验证继续保留在 [第二阶段报告](PHASE2_REPORT.md)。运行入口见 [复现命令](REPRODUCE.md)。

| 项目 | 现在提供什么 | 主要入口 |
|---|---|---|
| KVM VM Exit Analyzer | 主机检查、按 QEMU 进程采集、事件/退出原因统计、vCPU 调度与 entry/exit 配对、CSV、测试样本 | [使用说明](kvm_exit_analyzer/README.md) |
| QEMU VirtIO Lab | QOM 生命周期、modern PCI 绑定、单 virtqueue、echo 协议、边界检查、reset、trace、源码集成工具 | [使用说明](qemu_virtio_lab/README.md) |

KVM 数据来自真正的 Linux Guest 和 WSL2 嵌套 KVM。VirtIO 同时有 qtest 设备测试和实际 Guest 功能驱动测试；后者在 split/packed 下均完成请求、回调、并发调用、超时恢复与持有 FD 时的热插拔。[开发计划](DEVELOPMENT_PLAN.md) 区分完成范围与未来扩展。

## 立即运行离线示例

需要 Python 3.10+；分析器只使用标准库。以下命令从本目录执行，输出目录必须尚不存在：

```bash
python3 kvm_exit_analyzer/analyze_trace.py \
  kvm_exit_analyzer/tests/fixtures/synthetic_trace.txt \
  --out runs/demo
python3 -m unittest discover -s kvm_exit_analyzer/tests -v
```

在 Linux 上运行 Python 测试、Shell 语法检查和 C 协议 ASan/UBSan 测试：

```bash
bash run_offline_tests.sh
```

生成 `event_counts.csv`、`exit_reasons.csv`、`events_per_second.csv`、`intervals.csv`、`latency_summary.csv`、`summary.json` 和 `report.md`。自带数据明确标注为 **synthetic**，仅验证计算逻辑。

建议在 Linux 文件系统内克隆仓库和构建 QEMU。桌面交付目录保留了完整源码、论文、运行资产与原始验证证据；GitHub 仓库保留源码、测试、构建脚本、报告、汇总 CSV 和诊断日志。原始 trace、逐事件间隔 CSV、Guest 镜像、构建产物及论文文件不随 Git 上传，具体范围见 [证据目录说明](evidence/README.md)。

## 目录

```text
Hypervisor-Projects/
  kvm_exit_analyzer/       检查、采集、分析、测试与实验说明
  qemu_virtio_lab/         QEMU 设备、协议、集成工具与测试
  evidence/               实际验证的汇总结果、诊断日志及合成示例报告
  DEVELOPMENT_PLAN.md     阶段计划与未完成工作
  PERFORMANCE_REPORT.md   本次真实实验结论
  PHASE3_REPORT.md        当前完成状态与证据
  docs/                  原始报告模板
  VALIDATION.md           验证范围与当前环境限制
  SOURCES.md              上游源码和官方文档
```

## 证据边界

- KVM 项目使用内核 tracepoint 进行观测，未修改 KVM 内核。entry→exit 和 exit→entry 是墙钟间隔，不是纯 guest CPU 时间或纯 VM Exit 处理耗时。
- VirtIO 项目属于 QEMU/VMM 设备模拟层，未实现新的 Hypervisor。
- TCG 可验证设备功能；其性能不能代表 KVM。当前没有真实 VFIO/IOMMU PCI 直通验证。
- 私有实验 device ID 63 不是 OASIS 分配或保留给本项目的 ID，不能宣称标准兼容设备。
- 不提供硬件重跑、写卡或生产部署自动化。自定义 virtio-lab 驱动仅在隔离 Linux Guest 中加载；CPU/磁盘/网络矩阵使用标准 Linux 驱动，所有磁盘写入都位于专用虚拟镜像内。

源码按 GPL-2.0-or-later 提供，许可证正文见 [LICENSE](LICENSE)；QEMU 上游代码继续遵循其各文件的许可证。
