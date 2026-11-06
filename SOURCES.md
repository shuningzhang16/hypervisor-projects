# 上游依据

2026-11-06 Guest 驱动：[Writing Virtio Drivers](https://docs.kernel.org/driver-api/virtio/writing_virtio_drivers.html) 与 [Building External Modules](https://docs.kernel.org/kbuild/modules.html)。实际编译依据为下载的 Ubuntu `5.15.0-194-generic` headers/Module.symvers 和对应内核，包版本 `5.15.0-194.204`；未用滚动文档冒充已编译 API。

2026-11-05 第三阶段：[perf_event_open Linux 手册](https://man7.org/linux/man-pages/man2/perf_event_open.2.html) 用于按线程绑定 tracepoint 的 PID namespace 映射；[OASIS VirtIO 1.2 packed virtqueue](https://docs.oasis-open.org/virtio/virtio/v1.2/virtio-v1.2.html) 用于 packed flags、wrap、Buffer ID 与通知测试。QEMU 行为仍对照实际 9.2.0 源码。Guest 内核和标准模块来自本机 WSL 安装，对应 [Microsoft WSL2 Linux kernel 项目](https://github.com/microsoft/WSL2-Linux-Kernel)，具体本机路径和 uname 记录在 Guest 构建日志中。

2026-11-05 补充：[KVM API](https://docs.kernel.org/virt/kvm/api.html)、[QTest 框架](https://www.qemu.org/docs/master/devel/testing/qtest.html)、[QMP 参考](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html)、[actions/checkout 官方仓库](https://github.com/actions/checkout)。本轮新增微型 workload 使用 KVM API；设备测试仍针对本地已编译的 QEMU 9.2.0。

查阅日期：2026-11-04。接口实现以固定源码版本为准，滚动文档用于概念说明。

- [Linux upstream](https://github.com/torvalds/linux)
- [Linux v6.12 KVM x86 tracepoint definitions](https://github.com/torvalds/linux/blob/v6.12/arch/x86/kvm/trace.h)：核对 entry、exit、PIO 文本与字段；运行时始终保存本机 format。
- [Kernel event tracing](https://docs.kernel.org/trace/events.html)：available_events、format 和事件过滤。
- [KVM techniques（用户提供入口）](https://www.kernel.org/doc/html/latest/virt/kvm/techniques.html)：本次文档工具未能访问，未将该页内容作为已核实依据。
- [trace-cmd record 手册](https://www.trace-cmd.org/Documentation/trace-cmd/trace-cmd-record.1.html)：record、事件选择、过滤、clock 与独立 instance。
- [trace-cmd report 手册](https://www.trace-cmd.org/Documentation/trace-cmd/trace-cmd-report.1.html)：report、纳秒时间戳与插件选项。
- [QEMU upstream](https://github.com/qemu/qemu)
- [QEMU v9.2.0 VirtIO header](https://github.com/qemu/qemu/blob/v9.2.0/include/hw/virtio/virtio.h)
- [QEMU v9.2.0 virtio-rng.c](https://github.com/qemu/qemu/blob/v9.2.0/hw/virtio/virtio-rng.c)
- [QEMU v9.2.0 virtio-rng-pci.c](https://github.com/qemu/qemu/blob/v9.2.0/hw/virtio/virtio-rng-pci.c)
- [QEMU v9.2.0 PCI transport](https://github.com/qemu/qemu/blob/v9.2.0/hw/virtio/virtio-pci.c)
- [QEMU Device Emulation](https://www.qemu.org/docs/master/system/device-emulation.html)
- [QEMU Writing VirtIO backends](https://www.qemu.org/docs/master/devel/virtio-backends.html)
- [QEMU VirtIO devices](https://www.qemu.org/docs/master/system/devices/virtio/)
- [Linux VirtIO driver API](https://www.kernel.org/doc/html/latest/driver-api/virtio/virtio.html)

全局 Codex 工作规则的位置按 [官方 AGENTS.md 说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md) 核对。本机全局文件已包含用户要求，因此未重复改写。
