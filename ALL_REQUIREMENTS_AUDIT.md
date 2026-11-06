# 全部要求核对：原始功能清单与实际验证范围

核对日期：2026-11-06。此表针对用户最初提出的两个项目及全部目标，不以“某一轮工作结束”替代整体完成。

此前助手把 Guest 功能驱动也归入“真实驱动”排除，造成原始目标中的 Guest 功能交互缺口。用户了解其用途并明确要求验证后，该驱动、客户端和真实 Guest 测试已补齐。[Guest 验证报告](GUEST_DRIVER_REPORT.md) 提供新增证据。原始功能清单现有实现与本机运行验证；这不包含迁移、生产部署、物理直通或未执行的云端 CI。

## 项目 1：KVM VM Exit Tracing & Performance Analyzer

| 原始要求 | 当前状态 | 已有证据及限制 |
|---|---|---|
| 检查 /dev/kvm 与 KVM trace events | 完成 | check_host.sh；实际 KVM 启动与事件录制成功 |
| Linux Guest CPU、磁盘、网络 workload | 完成 | 48 次真实 Linux Guest 实验；标准内核驱动，WSL2 嵌套 KVM |
| entry、exit、MMIO、PIO 采集 | 完成 | 24 份 trace.dat；181,585 个工作窗口内 kvm_exit |
| 退出原因、频次、每秒事件数、CSV | 完成 | analyze_trace.py 与每次 analysis 输出 |
| sched_switch、sched_wakeup 与调度延迟 | 完成 | 分运行/TID 的 wakeup→run、preempt→run 与分位数 |
| vCPU、内存、设备模型、workload 对照 | 完成短时实验 | 1/2/4 vCPU、256/512 MiB、virtio-blk/AHCI、virtio-net/e1000，3 秒 × 3 次；不能称为生产级性能定论 |
| 可复现采集、CSV、性能报告 | 完成 | [复现说明](REPRODUCE.md)、[性能报告](PERFORMANCE_REPORT.md)、[原始结果](evidence/phase3/linux-report/summary.json) |

项目 1 的原始功能清单已有实现和运行证据。原生 Linux 目标服务器、长时间业务负载、CPU 绑定与宿主隔离属于尚未做的更强性能验证；不能从当前嵌套 KVM 短测推导这些结论。

## 项目 2：QEMU VirtIO Device Model

| 原始要求 | 实现状态 | 验证状态 |
|---|---|---|
| 1. QOM 注册，派生 TYPE_VIRTIO_DEVICE | 完成 | 已在 QEMU 9.2.0 编译、创建设备 |
| 2. realize / unrealize | 完成 | qtest 启停、32 次真实 Linux Guest PCIe 添加/移除 |
| 3. device ID、feature、config | 完成 | 私有实验 ID 63；config 与现代 transport 协商通过 |
| 4. virtqueue / descriptor chain | 完成 | split、packed、SG、间接 descriptor 与异常链测试 |
| 5. 长度、方向、边界检查 | 完成 | 协议 ASan/UBSan 与实际 QEMU qtest 错误路径；不是对全部恶意输入的安全证明 |
| 6. 响应、used ring、通知 Guest | 完成 | qtest 检查响应/used ring/ISR；实际 Guest 驱动完成请求提交、中断回调和用户态结果核对 |
| 7. reset / 未完成请求清理 | 完成并验证 | qtest 与 Guest 重绑定/重载通过；注入未通知请求，验证超时后 reset/detach/del_vqs 回收、拒绝复用与恢复；打开 FD 移除与卸载保护通过 |
| 8. trace 与 notify→completion 延迟 | 完成 | 保留后端 trace；另新增 KVM Guest 提交→回调及用户 ioctl→返回 CSV，每种 ring 1000 个样本；分别标明测量环境 |
| 总目标中的 Guest 驱动交互 | **已补齐** | TCG split/packed 基础测试；KVM 两种 ring 完整测试，共 4328 个设备完成响应，包含错误、并发、超时、reset 与卸载 |

设备端 qtest 和真实 Guest 驱动端到端验证分别保存，不再用前者替代后者。Guest 驱动目标为已测试的 Ubuntu 5.15.0-194，运行于本机 WSL2 嵌套 KVM；没有把这些结果扩展为所有内核版本或所有宿主环境的兼容性结论。

## 没有完成的扩展，不能冒充原始清单已要求

- 迁移：设备仍显式不可迁移，只验证了拒绝；原始八项清单未要求迁移实现。
- 云端 CI / 发布：有 CI 配置和本地测试，没有云端运行或部署；原始需求没有指定远程仓库或发布目的地。
- 生产耐久与整体安全：已完成约十分钟、1,049,088 个批量请求的队列测试；未证明长期生产可靠性，未对整个 QEMU 启用 sanitizer 或完成安全审计。
- 真实 VFIO/IOMMU 直通：没有做，原始需求已经明确无实体 PCI 设备时不能声称完成。

上述扩展的未完成事实继续保留。原始清单中此前明确缺少的 Guest 功能交互已补齐；不以此宣称全部企业生产能力都已实现。
