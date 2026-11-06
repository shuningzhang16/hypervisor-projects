# 真实 Linux Guest 驱动验证

完成日期：2026-11-06。已补齐此前缺少的 virtio-lab Guest 功能驱动、用户态测试程序和实际请求/中断链路。自定义驱动只加载进实验 Guest，没有加载到 WSL/Windows Host。[源码与运行说明](qemu_virtio_lab/guest/README.md)

## 实际结果

| 环境 | 结果 | 证据 |
|---|---|---|
| TCG + split ring | Guest 内正常/错误请求、配置与真实完成回调通过 | [摘要](evidence/guest-driver/tcg-smoke/summary.json) |
| TCG + packed ring | Guest 确认协商 packed；同样的基础测试通过 | [摘要](evidence/guest-driver/tcg-packed-smoke/summary.json) |
| KVM + split ring | 完整测试通过，2,164 个设备完成响应，26 个检查结果 | [摘要](evidence/guest-driver/kvm-split-ready/summary.json)、[Guest 日志](evidence/guest-driver/kvm-split-ready/guest/serial.log) |
| KVM + packed ring | 完整测试通过，2,164 个设备完成响应，26 个检查结果 | [摘要](evidence/guest-driver/kvm-packed-ready/summary.json)、[Guest 日志](evidence/guest-driver/kvm-packed-ready/guest/serial.log) |
| 构建与独立核对 | 内核模块 kbuild W=1、静态 C 客户端严格编译通过；原始 CSV 分位数、trace 完成计数、构建源码一致性已核对 | [构建日志](evidence/guest-driver/build-ready.log)、[核对结果](evidence/guest-driver/verification.json) |

Guest 内核：Ubuntu `5.15.0-194-generic`，包版本 `5.15.0-194.204`。WSL Host 仍为原有内核，QEMU 仍为已编译的 9.2.0，设备模型 C 源码和原有迁移拒绝行为未改。[包来源与版本日志](evidence/guest-driver/kernel-packages.log)

## 完整测试覆盖什么

每套 KVM 实验均执行：

- 读取 config、确认 ring 格式；0/5/4096 字节回声与实际中断回调。
- 不支持的 opcode、非法 flags、响应空间不足；驱动拒绝超长输入、过短响应头、未知 ioctl 和无效用户指针。
- 4 个调用线程、1,024 个变长请求，逐个验证内容；驱动内部明确串行处理。
- 1,000 个 32 字节回声延迟样本，数据在测量完成后才输出到串口。
- 8 次 unbind/bind（设备 reset/重新初始化）和 8 次模块卸载/重载，每次重新执行请求检查。
- 故意跳过 queue kick，使真实已入队请求超时；确认返回 `ETIMEDOUT`、后续请求 `EIO`，重载后恢复。
- 保持字符设备 FD 打开，确认普通卸载被拒绝；执行 PCIe 移除，旧 FD 得到 `ENODEV`；重新添加设备后等待节点就绪并再次成功通信。
- 最后卸载确认模块与设备节点消失，再加载并通信；扫描 Guest dmesg 未发现 BUG/WARNING/Oops/panic 等目标错误标记。

这些是实际 Linux 内核驱动和用户程序的结果，qtest 未参与本轮 Guest 请求提交。

## Guest 端到端延迟

单位为 µs，每种队列 1,000 个样本。开启了 QEMU 后端 trace；运行于 WSL2 嵌套 KVM，没有隔离 Host 背景负载，因此不作队列性能排名。

| 队列 / 指标 | P50 | P95 | P99 |
|---|---:|---:|---:|
| split：提交→中断回调 | 109.297 | 251.949 | 433.208 |
| split：用户态 ioctl→返回 | 152.610 | 327.186 | 537.682 |
| packed：提交→中断回调 | 78.679 | 283.829 | 484.640 |
| packed：用户态 ioctl→返回 | 116.291 | 545.917 | 814.036 |

[split 原始 CSV](evidence/guest-driver/kvm-split-ready/latencies.csv) / [统计](evidence/guest-driver/kvm-split-ready/latency-summary.json)；[packed 原始 CSV](evidence/guest-driver/kvm-packed-ready/latencies.csv) / [统计](evidence/guest-driver/kvm-packed-ready/latency-summary.json)。另有提交→等待线程返回这一中间指标。

## 失败处理记录

第一次完整 split 测试在热插拔重新添加后失败：脚本固定等待 1 秒，Guest 尚未完成异步 PCI 初始化，设备节点不存在。保留了该次日志和已完成的测量，没有把失败运行计入最终通过次数。

修复仅把固定睡眠改为最多 15 秒等待实际字符设备节点，再执行原测试。驱动检查、超时处理和错误判据没有放宽。修复后的新隔离 Guest 中两种队列均通过。[失败分析](evidence/guest-driver/FAILURE_ANALYSIS.md)、[原始失败](evidence/guest-driver/kvm-split/failure.txt)

## 边界

模块属于本地未签名 out-of-tree 实验模块，Guest 会记录预期的 taint 提示；没有修改模块签名强制策略。构建时缺少完整 vmlinux，kbuild 跳过 BTF 生成，模块加载和功能测试已经实际通过。

这不是生产认证、全输入空间安全证明或长期泄漏证明。没有在本轮启用整个 Guest 内核的 KASAN，也没有测试实体硬件驱动、VFIO 物理直通或迁移。云端 CI 和部署未执行。之前原始项目目标中的 Guest 功能交互缺口，本轮已有代码和运行证据闭合。
