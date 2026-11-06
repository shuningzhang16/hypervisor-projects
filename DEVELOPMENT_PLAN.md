# 开发计划

**2026-11-06 更新：** 用户明确同意进行 Guest 驱动验证后，已补齐 virtio-lab 功能驱动、用户态客户端和 split/packed 的真实 Guest 端到端验证。[Guest 驱动报告](GUEST_DRIVER_REPORT.md) 给出新证据；KVM Analyzer、54 次微型实验、48 次 Linux Guest 对比及既有设备测试继续保留。完整状态见 [全部要求核对](ALL_REQUIREMENTS_AUDIT.md)。

目前的证据链包括：内核 trace → CSV → 实测报告；C 设备实现 → QEMU 构建 → qtest；以及 Guest 用户程序 → 内核功能驱动 → VirtIO 设备 → 中断回调 → 用户程序结果。

| 阶段 | 状态 | 实际工作与交付 | 验证方式 |
|---|---|---|---|
| 1. 离线 Analyzer | 完成 | 文本解析、TID 配对、事件/原因 CSV、丢事件标记 | 14 个 Python 测试与实际 trace |
| 2. 真实 KVM 采集 | 完成 | Linux Guest CPU/磁盘/网络 workload；保存 trace.dat 与环境信息 | 48 次运行，24 份录制，无检测到的时序降级 |
| 3. 调度与性能报告 | 完成 | wakeup→run、preempt→run、entry/exit 墙钟间隔与分位数 | 1/2/4 vCPU、256/512 MiB、设备模型、tracing 开关、3 次重复 |
| 4. VirtIO 设备实现 | 完成 | QEMU 9.2.0、QOM/PCI、config/features、descriptor、reset、trace | 实际编译、协议 sanitizer、split/packed qtest |
| 5. 自定义 Guest 驱动 | 已实现并验证 | 内核模块、misc ioctl、用户态测试程序、构建与 Guest 包 | TCG 基础功能；KVM split/packed 完整测试，包含超时与卸载 |
| 6. 可靠性与作品报告 | 有界软件验证完成 | 异常链、重复 reset、index 回绕、持续队列与热插拔 | 见第三阶段日志；不等于生产环境耐久认证 |

## 项目 1：KVM Analyzer

已实现的核心以 Python 标准库和 Shell 为主，不引入数据库、Web 前端或常驻服务。解析分两遍读取文件，第一遍识别 vCPU TID，第二遍逐行分析。详细延迟直接写 CSV，内存保存线程状态和按秒计数；不把全部 trace 加载到内存。

后续换到其他目标环境时复用以下方法：

1. 在具备 `/dev/kvm` 权限、tracefs 和 trace-cmd 的 Linux 主机执行真实采集。保存 Guest 镜像来源、kernel/QEMU/trace-cmd 版本、完整启动参数、CPU affinity 和 workload 命令。
2. 确认报告中的 exit reason 来自所采集内核的事件格式；numeric reason 保留 ISA，不跨 Intel VMX/AMD SVM 混合映射。
3. 对 scheduler 事件确认使用跨 CPU 可比较的 trace clock。若启用 CPU pinning，记录绑定和 host 其他负载。
4. 统计平均值之外的分位数时，从 `intervals.csv` 按实验、TID、metric 分组计算，不把不同阶段混在一起；原始输入保持可追溯。
5. 对比开启/关闭 tracing 的 workload 吞吐，量化观测扰动。用 `perf`、QEMU trace 或用户态采样进一步拆解 exit→entry 墙钟间隔，不将该间隔直接归因于 KVM。

## 项目 2：VirtIO Lab

当前协议只有 ECHO，队列大小 64，payload 上限 4096 字节。先把生命周期与错误路径做清楚，再考虑新命令、多队列或异步后端。transport 通用 feature bits 由 QEMU 处理，本版本无设备专属 feature bit。

以下 Guest 功能驱动步骤已在 `qemu_virtio_lab/guest` 中实现；具体请求接口采用 misc ioctl：

1. `virtio_driver.id_table` 匹配实验 device ID 63；仅在隔离测试 Guest 中加载。
2. probe 读取 config 中协议版本和最大长度，通过 `virtio_find_single_vq()` 创建队列。
3. 先支持单个在途请求：构造 16 字节 LE header，通过 `virtqueue_add_sgs()` 提交只读请求 SG 和可写响应 SG，再 `virtqueue_kick()`。
4. 回调中 `virtqueue_get_buf()` 获取完成项，检查 used length、status、length、request_id，唤醒等待者。
5. 超时不能直接释放仍由设备持有的 buffer；先 reset/quiesce，再回收。remove 路径 reset、删除队列并清理未完成请求。
6. 增加零长度、上限长度、不支持 opcode、错误长度、多个 SG、reset/reprobe 测试。

后续扩展包括设备状态迁移、目标主机生产负载和更长时间耐久验证。Guest 功能驱动端到端、标准 PCIe 热插拔、持续队列与本地自动化已验证，云端 CI 尚未执行。当前不支持迁移，QEMU 通过 `unmigratable` 明确拒绝；这不是一个已经冻结的迁移 ABI。

## 交付与岗位展示

最终作品应包含：原始 trace 与说明、CSV 和实验结论、QEMU 源码 diff、编译日志、协议与 Guest 测试日志、失败案例的最小复现和修复记录。简历描述采用已证明的事实，例如“实现基于 KVM tracepoint 的 vCPU 调度与退出分析工具”，或“实现并验证 QEMU 自定义 VirtIO 设备”。不要写“实现 KVM 内核”或“完成真实设备直通”。
