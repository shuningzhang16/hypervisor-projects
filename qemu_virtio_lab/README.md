# QEMU VirtIO Lab

2026-11-06：已新增 [Linux Guest 功能驱动与客户端](guest/README.md)，在真实 Guest 中验证 split/packed 请求、IRQ 回调、错误、超时、reset、卸载与打开 FD 热插拔；[结果](../GUEST_DRIVER_REPORT.md)。

2026-11-05：split ring、异常链、间接 descriptor、通知抑制与 QMP reset/迁移拒绝均已验证；新增 packed ring、Linux Guest PCIe 热插拔和持续队列测试。当前结果见 [第三阶段报告](../PHASE3_REPORT.md) 和 [复现命令](../REPRODUCE.md)。设备 C 代码与已编译的 9.2.0 补丁保持一致。

这是面向 **QEMU v9.2.0** 的实验设备实现。`virtio-lab.c` 需要 QEMU 内部头文件和构建环境，不能当成独立 C 程序编译。相比空 API 骨架，本包提供完整的最小 echo 处理、modern PCI 绑定和源码集成步骤；是否编译/运行成功以根目录 [VALIDATION.md](../VALIDATION.md) 为准。

## 结构

| 文件 | 职责 |
|---|---|
| virtio-lab.c / .h | QOM、realize/unrealize、feature/config、队列回调、reset |
| virtio-lab-pci.c | modern-only PCI transport 绑定 |
| lab-protocol.c / .h | 独立可测试的 LE wire protocol 与 echo |
| integrate.py | 将代码和 Meson/Kconfig/trace/设备 ID 注册接入独立 QEMU 9.2.0 副本 |
| virtio-lab-qemu-9.2.0.patch | 与实际编译源码一致的统一 diff，可供 Git 审阅/应用 |
| tests/qtest_smoke.py | 通过 QEMU qtest 实际访问 PCI、协商 features 并提交 descriptor |
| tests/qtest_packed.py / qtest_soak.py | packed ring 与同一进程中的有时限持续压力 |
| tests/qmp_hotplug.py | 由真实 Linux Guest 确认 PCIe 枚举/移除 |
| meson.build.example / Kconfig.example / trace-events.example | 具体构建和 trace 注册片段 |
| tests/test_protocol.c | 协议正常/错误长度/容量/未知 opcode 测试 |

## 固定版本并构建

这里选择 9.2.0 是为了明确 API 目标，不表示它是最新版本或建议用于生产。需要升级时先更新版本并重新验证 `include/hw/virtio/virtio.h`、`virtio-rng.c` 和 transport API。

```bash
sudo apt install build-essential git python3 python3-venv ninja-build \
  pkg-config libglib2.0-dev libpixman-1-dev libslirp-dev
git clone --depth 1 --branch v9.2.0 https://github.com/qemu/qemu.git qemu-lab-9.2.0
python3 /path/to/Hypervisor-Projects/qemu_virtio_lab/integrate.py qemu-lab-9.2.0
cd qemu-lab-9.2.0
mkdir build && cd build
../configure --target-list=x86_64-softmmu --disable-docs \
  --enable-trace-backends=log
ninja -j4 qemu-system-x86_64
./qemu-system-x86_64 -device help | grep virtio-lab
```

也可以使用 QEMU 官方的 `qemu-9.2.0.tar.xz`。集成器只要求 VERSION 为 9.2.0，不使用额外 hash。请对独立源码副本操作；若目标已有不同的 `virtio-lab` 文件，先用 Git 审阅并合并，避免覆盖已有工作。Meson 片段必须放在 source set 被加入 `specific_ss` 之前，不能随意追加在文件末尾。

`integrate.py` 还会在 QEMU 的 VirtIO PCI ID 信息表与设备名称表中增加本实验项；仅有设备 C 文件和 Meson 注册不足以覆盖这一版本的 ID 查询路径。

也可在干净的 v9.2.0 源码目录执行 `git apply /path/to/virtio-lab-qemu-9.2.0.patch`，然后正常配置构建。补丁与集成器二选一即可。

## 启动

设备模型开发先使用 TCG，自己的 Linux Guest 镜像必须已安装系统：

```bash
./qemu-system-x86_64 -machine q35,accel=tcg -m 1024 -smp 1 \
  -drive file=/path/to/guest.qcow2,format=qcow2,if=virtio,snapshot=on \
  -device virtio-lab-pci \
  -trace 'enable=virtio_lab_*' -D virtio-lab.log
```

标准 Linux 内核没有内置本实验设备的功能驱动；本项目现在提供 `guest/virtio_lab.c` 外部模块与用户态客户端，已经在专用 Guest 中完成实际 virtqueue 请求和回调验证。构建和运行见 [Guest 说明](guest/README.md)。实验 ID 和驱动仅用于本项目隔离测试环境。

## 协议与设备行为

实验 VirtIO device ID 为 **63 (0x3f)**，modern PCI device ID 为 `0x1040 + 63 = 0x107f`。这是本地测试选择，**不是 OASIS 分配或保留的私有 ID**，应避免与其他设备同时复用，不能发布为标准设备。

只读 config 为两个 little-endian u32：`protocol_version=1`、`max_payload=4096`。本协议没有设备专属 feature bit，QEMU 提供的 transport features 保留并进行协商。设备只注册 modern PCI 类型。

| 偏移 | Request（device-readable / OUT） | Response（device-writable / IN） |
|---|---|---|
| 0 | opcode:u16，1=ECHO | status:u32 |
| 2 | flags:u16，必须为 0 | status 的高 16 位 |
| 4 | payload_length:u32 | 实际 response payload_length:u32 |
| 8 | request_id:u64 | 相同 request_id:u64 |
| 16 | payload，最多 4096 bytes | ECHO payload 或空 |

status：0=OK，1=BAD_REQUEST，2=UNSUPPORTED，3=NO_SPACE。所有多字节值为 LE。请求总长度必须恰好为 16+payload_length；响应 used length 为真实写入的 header+payload，错误响应只写 header。

一个通用 virtqueue，最大 64 个 descriptor；默认 split，设置 `packed=on` 后可协商 packed ring，两条路径均经过测试。QEMU `virtqueue_pop` 负责 transport 层 chain/map 检查；设备随后验证 OUT/IN 方向以及长度，再通过 iov helpers 访问 SG，不直接把 Guest 地址当作 Host 指针。请求头或可写响应头不足时调用 `virtio_error`，请求 Guest reset，避免伪造成功完成。

每次处理最多 64 个元素，若仍有工作则通过 BH 继续，避免单次回调无限占用主循环。每个元素同步完成并释放，不跨回调保留 `VirtQueueElement`；reset 取消 BH 并由 VirtIO core 重置 ring，unrealize 删除 BH/队列并清理设备。

当前 migration 不支持，通过 `unmigratable` 明确拒绝。已验证标准 PCIe 热插拔；多线程 IOThread、实时性和敌对 Guest 的全部输入空间不在本次已证明的范围。

## Trace 指标

`virtio_lab_notify` 记录 QEMU 观察到 queue kick 的时间；`virtio_lab_complete` 记录 request_id、状态、used 字节和从最近一次 callback kick 到完成的间隔；`virtio_lab_reset` 记录 reset。时钟为 QEMU `QEMU_CLOCK_REALTIME`。

这是后端观察到的通知到完成时间，包含批处理/BH 等待；多个通知合并或重叠时不等于每个请求在 Guest 的提交延迟，也不含完整 Guest 中断处理时间。要测端到端延迟，还需 Guest 驱动的提交/完成时间戳。TCG 的这些数值只能用于该功能测试环境。

## 独立协议验证

```bash
mkdir -p build
gcc -std=c11 -Wall -Wextra -Werror -g -fsanitize=address,undefined \
  -I . lab-protocol.c tests/test_protocol.c -o build/test_protocol
./build/test_protocol
```

协议测试不覆盖 QEMU descriptor mapping、PCI feature negotiation、Guest 中断或迁移；这些需要 QEMU transport 测试和 Guest 测试补齐。

## 实际 PCI/virtqueue 验证

```bash
python3 /path/to/Hypervisor-Projects/qemu_virtio_lab/tests/qtest_smoke.py \
  /path/to/qemu-lab-9.2.0/build/qemu-system-x86_64 --out /path/to/new-qtest-results
```

这个测试用 TCG 初始化 QEMU 并暂停 vCPU，直接通过 qtest 操作模拟 Guest 内存和 PCI/MMIO。验证 device ID/config、VERSION_1 协商、分散 SG、echo、空与 4096 字节 payload、无效 opcode/length、响应容量、错误方向触发 NEEDS_RESET、used ring、ISR 状态和 reset 后恢复。

它不启动 Linux Guest，不执行实际 Guest 中断处理器，也不测 KVM 性能。QEMU stderr、设备 trace 和启动命令自动保存在指定新目录中。必须用普通 Python 运行，不使用会关闭测试断言的 `python -O`。
