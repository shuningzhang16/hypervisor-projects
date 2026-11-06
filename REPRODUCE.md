# 复现命令

从项目根目录运行。新结果目录必须不存在；旧日志不会作为新实验结果复用。Linux 需要 Python 3.10+、GCC、Bash；采集另需 trace-cmd、root、tracefs 和可用的 KVM。

## 离线测试

```bash
make test
# 或：bash run_offline_tests.sh
```

这只执行解析/统计单元测试、C 协议 sanitizer 测试以及 KVM workload 编译，不启动 VM，也不加载驱动。

## 实际 KVM 微型实验

```bash
mkdir -p build
gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread \
  kvm_exit_analyzer/workloads/kvm_microbench.c -o build/kvm_microbench
sudo bash kvm_exit_analyzer/check_host.sh
sudo python3 kvm_exit_analyzer/run_experiments.py \
  --binary build/kvm_microbench --out runs/kvm-matrix \
  --modes cpu pio mmio --vcpus 1 2 4 --repeats 3 --seconds 2 --include-untraced
python3 kvm_exit_analyzer/summarize_experiments.py runs/kvm-matrix --out runs/kvm-report
```

程序只使用 `/dev/kvm` 用户态 API，分配 64 KiB Guest RAM，不使用磁盘镜像。CPU 模式在 PIO 前执行 60,000 次减计数；PIO 访问实验端口 0xe9；MMIO 访问未映射为 RAM 的 0xa0000/1 地址。每次返回用户态后睡眠 1000 µs，因此这是可控观测实验，不是最大吞吐 benchmark。

执行器在独立 trace instance 中通过 marker 获得线程外层 TID，适用于本次 WSL 环境；采集开始后才发送 SIGUSR1 释放等待的 workload。该协作握手只由执行器使用。**不要对未设置 SIGUSR1 等待逻辑的 QEMU/其他进程使用 `--signal-start`**。每个失败目录保存日志且不自动重试。

原生 Linux 上采集已有 QEMU：

```bash
sudo bash kvm_exit_analyzer/collect_kvm_trace.sh --pid QEMU_PID --seconds 30 --output runs/qemu-01
python3 kvm_exit_analyzer/analyze_trace.py runs/qemu-01/trace.txt \
  --out runs/qemu-01-analysis --source-kind real-kvm \
  --diagnostics runs/qemu-01/collection.log --diagnostics runs/qemu-01/report.stderr
```

嵌套 PID namespace（含本次 WSL）中，普通 QEMU 的 `/proc` TID 不能直接用于 tracepoint 过滤。需要在宿主初始 PID namespace 中运行采集，或显式传 `--trace-tids OUTER_TID1,OUTER_TID2`。下述 Linux Guest 执行器使用 perf tracepoint 对指定本地 TID 作短期映射；它不修改 QEMU 或内核。

## Linux Guest CPU / 磁盘 / 网络矩阵

本次验证使用现成 WSL Linux 6.6.114.1 内核、静态 BusyBox，以及同版本未压缩的标准 `virtio_blk.ko`、`e1000.ko`；没有自定义驱动。构建脚本需要 GCC 的静态 libc、cpio、gzip、e2fsprogs。其他发行版需要提供与模块匹配且包含串口、VirtIO PCI/net、AHCI、ext4、devtmpfs 的可启动 x86-64 内核。

```bash
# 本机 WSL 的实际输入；输出路径必须不存在。
bash scripts/build_linux_guest.sh \
  '/mnt/c/Program Files/WSL/tools/kernel' \
  /lib/modules/6.6.114.1-microsoft-standard-WSL2 \
  /var/tmp/my-linux-guest

QEMU=/var/tmp/hypervisor-build.0923va/qemu-9.2.0/build/qemu-system-x86_64
sudo python3 kvm_exit_analyzer/run_linux_matrix.py \
  --qemu "$QEMU" --assets /var/tmp/my-linux-guest \
  --out /var/tmp/my-linux-matrix --seconds 3 --repeats 3
python3 kvm_exit_analyzer/summarize_linux_matrix.py \
  /var/tmp/my-linux-matrix --out runs/linux-report
```

脚本运行 6 种配置、8 个配置/workload 组合，tracing 开/关各重复 3 次，共 48 次。1/2/4 vCPU、256/512 MiB、virtio-blk/AHCI、virtio-net/e1000 均有单参数对照。每台 VM 从专用空白镜像复制独立磁盘，TCP 服务只监听 WSL `127.0.0.1`。工作负载执行细节见 [性能报告](PERFORMANCE_REPORT.md)。

采集要有 root/perf tracepoint 权限以及可读 tracefs；映射期间 VM 从 `-S` 恢复启动，`perf_tid_map` 只记录指定线程的 `raw_syscalls:sys_enter`，取得 `common_pid` 后关闭。采集器通过 `--ready-file` 通知执行器事件已启用，然后才发送 Guest workload 命令；不会给 QEMU 发送 SIGUSR1。

本机 trace-cmd 在独立目录解包，未全局安装；可这样使用原依赖：

```bash
sudo env \
  PATH=/var/tmp/hypervisor-trace-tools.y8gmsu/root/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LD_LIBRARY_PATH=/var/tmp/hypervisor-trace-tools.y8gmsu/root/usr/lib/x86_64-linux-gnu \
  python3 kvm_exit_analyzer/run_linux_matrix.py \
    --qemu "$QEMU" --assets /var/tmp/my-linux-guest \
    --out /var/tmp/my-linux-matrix --seconds 3 --repeats 3
```

桌面 `artifacts/linux-guest.tar.gz` 是本机已测试 Guest 资产包，包含 kernel、initramfs、空白 disk.img、perf 映射工具和构建来源记录。可解包到新的 Linux 目录作为 `--assets` 使用；它是 x86-64 Linux 运行资产，不是 Windows 可执行程序。源码与构建步骤仍在本项目中。

## QEMU 构建与软件验证

构建依赖可按 Ubuntu/Debian 说明安装：`build-essential python3-venv ninja-build pkg-config libglib2.0-dev libpixman-1-dev libslirp-dev`。其中 libslirp 用于 Linux Guest 的 user-net 路径。构建脚本只往指定目录写文件，不执行系统安装。

```bash
bash scripts/build_qemu.sh /path/on/linux/filesystem/qemu-lab
QEMU=/path/on/linux/filesystem/qemu-lab/qemu-9.2.0/build/qemu-system-x86_64
make qtest QEMU="$QEMU" OUT=runs/qtest
make stress QEMU="$QEMU" OUT=runs/qtest-stress
make lifecycle QEMU="$QEMU" OUT=runs/lifecycle
make packed QEMU="$QEMU" OUT=runs/packed
make soak QEMU="$QEMU" OUT=runs/soak
python3 qemu_virtio_lab/tests/qmp_hotplug.py --qemu "$QEMU" \
  --assets /var/tmp/my-linux-guest --out runs/hotplug --cycles 32
python3 qemu_virtio_lab/analyze_device_trace.py runs/qtest-stress/device-trace.log \
  --out runs/virtio-trace-report --label 'TCG qtest; trace logging enabled'
```

压力测试默认提交 65,568 个请求并执行 128 次 reset，逐项检查 payload、used ring、错误状态和通知抑制。它不启动 Linux Guest；不能证明 Guest 驱动或端到端中断行为。

`packed` 协商 RING_PACKED，验证 4,096 次请求、SG 跨 ring wrap、通知抑制和 reset/异常恢复。`soak` 在同一个 QEMU 进程中连续运行至少 600 秒，每批 65,568 请求并记录 RSS，当前批结束后才退出，因此可能略超过设定时长。`hotplug` 运行真实 Linux Guest，以 Guest sysfs 枚举与 QMP DEVICE_DELETED 双方证据确认 32 次添加/删除；只使用内核原有 PCIe 和 virtio-pci transport 驱动。

Linux 文件系统上的日志通常比跨 Windows 挂载卷写入更适合时间测量。无论日志路径在哪里，启用 trace 都会扰动结果；报告必须说明 accelerator、批量方式和日志开关。

## 自定义 Linux Guest 功能驱动验证

现已提供真实内核模块与用户态客户端，构建、运行和接口说明见 [Guest 驱动说明](qemu_virtio_lab/guest/README.md)，实测结果见 [报告](GUEST_DRIVER_REPORT.md)。

```bash
bash scripts/prepare_driver_kernel.sh /var/tmp/lab-driver-kernel
bash scripts/build_guest_driver.sh /var/tmp/lab-driver-kernel/root /var/tmp/lab-driver-assets
sudo python3 qemu_virtio_lab/tests/guest_driver.py --qemu "$QEMU" \
  --assets /var/tmp/lab-driver-assets --out runs/driver-split
sudo python3 qemu_virtio_lab/tests/guest_driver.py --qemu "$QEMU" \
  --assets /var/tmp/lab-driver-assets --out runs/driver-packed --packed
```

驱动只在测试 Guest 的 `/init` 中加载；准备/构建脚本不安装 Host 内核或加载 Host 模块。`--accelerator tcg --smoke-only` 可运行无需 KVM 的基础验证。本地 `artifacts/virtio-lab-driver-guest.tar.gz` 与此前仅包含标准驱动的 `linux-guest.tar.gz` 分开保存；运行资产不随 Git 上传，克隆仓库后使用上面的脚本构建。

## CI 范围

`.github/workflows/software-tests.yml` 在 push/PR 时运行离线测试，手动 workflow_dispatch 时额外构建 QEMU 并运行 split/packed transport 与 lifecycle 测试。没有 KVM/实体硬件任务，没有发布步骤，也没有设置仓库合并门禁。各次云端执行状态以仓库 Actions 记录为准；此前报告中的 KVM 和 Guest 结果来自本地验证。
