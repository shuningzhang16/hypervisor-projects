# 实际验证记录

**2026-11-06 最新验证：** 已新增真实 Linux Guest 功能驱动测试，TCG 基础功能与 KVM split/packed 完整流程均通过。包括请求/中断、并发、超时、reset/reload、打开 FD 热移除及 Guest 端到端延迟。见 [最新报告](GUEST_DRIVER_REPORT.md)。以下阶段记录保留其原始时间与证据。

**2026-11-05 最新状态：** 当前完成范围见 [PHASE3_REPORT.md](PHASE3_REPORT.md)：已补完 Linux Guest CPU/磁盘/网络 48 次运行、packed ring、标准 PCIe 热插拔和持续队列验证。自定义 Guest/实体驱动仍按用户要求排除。下面保留第一阶段历史记录；[第二阶段](PHASE2_REPORT.md) 的原始证据也完整保留。

日期：2026-11-04。桌面源码：`E:\桌面\Hypervisor-Projects`。

## 已执行

| 验证项 | 结果 | 证据 |
|---|---|---|
| KVM 分析器定向单元测试 | 10/10 通过 | [offline/tests.log](evidence/offline/tests.log) |
| 合成 trace CLI → CSV/JSON/报告 | 通过；输入明确为 synthetic | [示例摘要](evidence/offline/synthetic-report/summary.json)、[事件 CSV](evidence/offline/synthetic-report/event_counts.csv) |
| Shell 脚本语法检查 | 通过 | 同一 offline 测试日志 |
| C 协议测试 | GCC `-Wall -Wextra -Werror` + AddressSanitizer/UndefinedBehaviorSanitizer 通过 | 同一 offline 测试日志 |
| QEMU x86_64-softmmu 完整构建 | QEMU 9.2.0 构建并链接成功；最终注册修复再次构建成功 | [完整编译日志](evidence/qemu-build.log)、[修复后编译日志](evidence/qemu-rebuild.log)、[版本](evidence/qemu-version.txt) |
| QEMU PCI/virtqueue 功能测试 | PCI/config、feature negotiation、SG/echo/边界、used ring/ISR、reset 恢复通过；最终清理无 GLib 警告 | [通过日志](evidence/qtest-final-console.log)；设备 trace 在本地 `evidence/qtest-final/device-trace.log` |
| 可应用补丁与文档链接 | 在原版 v9.2.0 文件的隔离副本中实际应用补丁，10 个结果文件逐字节等于已编译源码；相对文档链接可解析 | [检查日志](evidence/patch-and-links-final.log) |
| 当前 Linux Host 采集条件 | 不满足；未运行真实采集 | [host-check.log](evidence/host-check.log) |

Linux 验证环境：Ubuntu 22.04 WSL2、kernel `6.6.114.1-microsoft-standard-WSL2`、Python 3.10.12、GCC 11.4.0。QEMU 构建配置为 `x86_64-softmmu`，关闭 docs/GTK/SDL/VNC，使用 log trace backend；未进行系统安装。构建依赖 tomli 和 Meson 1.5.0 安装在隔离的虚拟环境中。

构建副本位于 WSL `/var/tmp/hypervisor-build.0923va/qemu-9.2.0`。该目录用于本次验证，可能被系统清理；桌面交付的代码、补丁、命令和证据可用于重新构建。

## 失败与修复

1. 本机 Windows Python 路径和 WSL 登录 PATH 有异常，改用 Linux 系统 Python/GCC 和进程内 PATH，未改全局环境。初次 `/tmp` 构建目录在后续调用中不可见，改用 `/var/tmp` 的独立构建副本。[记录](evidence/setup-failures.txt)
2. 初次 QEMU configure 缺少 tomli。在独立 venv 补充依赖后重新配置，不改 QEMU 检查逻辑。[原失败日志](evidence/qemu-configure.log)、[后续配置](evidence/qemu-configure-attempt-2.log)
3. 第一次 qtest 调用发生在链接完成前，二进制尚不存在；没有运行设备。第二次实际启动触发 `virtio_id_to_name` 的 device ID 越界断言。保留上游断言，在集成器中补齐 `virtio_device_names[63]` 注册，重编译后设备功能测试通过。[断言与 qtest 日志](evidence/qtest-attempt-2/stderr.log)
4. 首次通过的 qtest 在清理阶段出现 QEMU 的 `g_timer_elapsed` 日志警告；调整测试端资源关闭顺序，在 QEMU 退出后再关闭客户端 socket，功能逻辑未变。后续测试通过且不再出现该警告，结果保存在 `evidence/qtest-final`。
5. 第一次补丁检查发现新增文件缺少 `new file mode` 元数据，Git 将 `/dev/null` 误识别为输入路径。保留 [原补丁](evidence/patch-attempt-1.patch) 和 [失败日志](evidence/patch-and-links-check.log)，修正打包后重新在原版源码的隔离副本中应用成功；编译过的设备代码未因此改变。

## 尚未验证

- 当前用户无 `/dev/kvm` 读写权限，没有可读 tracefs，也未安装 trace-cmd。本次没有修改权限、挂载 tracing 或启动真实 KVM Guest/workload，因此没有真实 VM Exit 采集或性能数字。
- Analyzer 的 collector 仅做了语法和人工逻辑核对，没有宣称真实 trace-cmd 录制通过。跨内核/trace-cmd 文本兼容性需目标 Host 数据验证。
- qtest 在暂停的 TCG QEMU 中直接驱动 transport；没有启动 Linux Guest，没有 Guest 驱动测试或真正的 Guest 中断服务程序。
- 未验证迁移（设备明确标记不可迁移）、热插拔、长期并发压力、所有畸形 descriptor、packed ring、VFIO/IOMMU 或硬件 PCI 直通。

这份交付可以作为可审阅的项目起点。企业生产可用性需要继续完成 [开发计划](DEVELOPMENT_PLAN.md) 的真实 Guest、性能和可靠性阶段。

