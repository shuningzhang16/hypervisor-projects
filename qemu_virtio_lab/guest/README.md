# virtio-lab Linux Guest 驱动

这是给本项目 QEMU 软件设备使用的实验 Linux 内核模块。匹配未分配给本项目的实验 VirtIO ID 63，仅用于隔离 Guest；不是实体 PCI 硬件驱动。已在 Ubuntu Guest 内核 `5.15.0-194-generic`（包版本 `5.15.0-194.204`）、QEMU 9.2.0 上编译并运行。[实际验证报告](../../GUEST_DRIVER_REPORT.md)

## 文件与接口

- `virtio_lab.c`：设备识别、config、virtqueue、真实中断回调、misc 字符设备、超时和 remove。
- `lab_uapi.h`：本地实验 ioctl 接口；`LAB_IOC_INFO` 查询配置，`LAB_IOC_TRANSFER` 提交一次请求并返回结果。
- `lab_client.c`：正常/错误请求、并发调用、延迟、超时和打开 FD 移除测试。
- `init`：只放进 Guest initramfs，负责在 Guest 内加载标准 transport 和自定义模块，并接受测试命令。

设备节点为 `/dev/virtio-lab-virtioN`，权限 `0600`。用户程序提交 opcode、flags、request_id、payload 与响应容量；驱动建立请求头/可选 payload/可写响应的 SG，通知队列，等待中断回调消费 used buffer。协议状态保持原设备定义，最大 payload 4096 字节。

同一设备最多一个在途请求，多个调用者通过 mutex 串行化；队列 producer/consumer 用 IRQ-safe spinlock 保护。该实现没有宣称多队列或并行后端吞吐。

## 生命周期与错误处理

驱动检查用户缓冲区、消息长度、响应容量、返回 request_id、status 和 used length。缺少有效响应时返回错误，不将未完成请求当作成功。

超时路径先 reset 设备，detach 未完成的 buffer，再删除队列并同步 IRQ，最后释放请求内存。超时后设备实例标记失败，后续请求返回 `EIO`；通过重绑定或卸载/重载重新初始化。默认超时 1000 ms，允许 50–5000 ms。测试参数 `test_skip_kick=1` 故意将请求放入队列但不通知设备，只用于隔离 Guest 的超时验证，正常运行不启用。

打开文件持有模块和设备引用。普通 `rmmod` 在 FD 打开时被拒绝；PCIe 移除会停止设备并阻止新打开，旧 FD 后续 ioctl 返回 `ENODEV`，最后一次 close 才释放实例。没有使用强制卸载。

## 构建与运行

从项目根目录，在 Ubuntu Linux/WSL 执行：

```bash
bash scripts/prepare_driver_kernel.sh /var/tmp/lab-guest-kernel
bash scripts/build_guest_driver.sh /var/tmp/lab-guest-kernel/root /var/tmp/lab-driver-assets
QEMU=/path/to/qemu-9.2.0/build/qemu-system-x86_64

# TCG 基础功能，不需要 /dev/kvm。
python3 qemu_virtio_lab/tests/guest_driver.py --qemu "$QEMU" \
  --assets /var/tmp/lab-driver-assets --out runs/guest-tcg \
  --accelerator tcg --smoke-only

# 有 KVM 权限的 Linux 用户运行；按主机权限需要时使用 sudo。
sudo python3 qemu_virtio_lab/tests/guest_driver.py --qemu "$QEMU" \
  --assets /var/tmp/lab-driver-assets --out runs/guest-split
sudo python3 qemu_virtio_lab/tests/guest_driver.py --qemu "$QEMU" \
  --assets /var/tmp/lab-driver-assets --out runs/guest-packed --packed
```

准备脚本只下载并解包包文件，构建脚本只在指定的新目录写入。它们不安装 Host 内核、不执行 Host `insmod`，不会改变 Host 启动配置。需要 GCC、make、binutils、静态 libc、cpio、gzip、BusyBox static，以及可以下载指定 Ubuntu 软件包的 apt 源。

本地完整交付目录中，也可将 `artifacts/virtio-lab-driver-guest.tar.gz` 解压到新的 Linux 目录，将该目录传给 `--assets`。运行包不随 Git 上传，克隆仓库后按上面的步骤构建。其中 kernel/initramfs/disk 由 QEMU 使用，单独附带的 `.ko` 是 Guest 版本的模块，不能在 Host 上加载。

## 测量含义

`latencies.csv` 保存 Guest 同一 monotonic 时钟域下的三个值：驱动提交→回调、提交→等待返回、用户态 ioctl 调用→返回。32 字节 payload，通过固定大小 ioctl 结构传递；系统调用拷贝、Guest 调度、KVM/QEMU 和中断都可能影响总延迟。

测量后才输出串口 CSV；本次 QEMU 后端 trace 日志开启。数据用于解释完整链路，单次短测不能证明某种队列普遍更快。TCG 仅用于基础功能，性能表只引用 KVM 实验。

官方依据：[Linux VirtIO 驱动说明](https://docs.kernel.org/driver-api/virtio/writing_virtio_drivers.html)、[外部模块构建](https://docs.kernel.org/kbuild/modules.html)。实际接口以已测试的 5.15.0-194 headers 为准。
