# Linux Guest 实验结果

完成 48/48 次运行、24 对 tracing 开关对照；工作负载窗口内共 181,585 个 kvm_exit。

QEMU 9.2.0；WSL2 嵌套 KVM；Guest 使用本机 Linux 6.6.114.1 内核与标准驱动。
每个配置先预热 1 秒，每次测量 3 秒、计划重复 3 次，逐次交替 tracing 开关顺序。
未绑定 CPU；宿主 Windows/WSL 后台负载与调频未隔离。以下是本环境的短时观测，不是设备额定性能。

| 配置 | 工作负载 | tracing | 次数 | 平均速率 | 最小 | 最大 |
|---|---|---|---:|---:|---:|---:|
| ahci | disk | False | 3 | 5.501 MiB/s | 3.349 | 7.508 |
| ahci | disk | True | 3 | 4.735 MiB/s | 3.866 | 6.124 |
| e1000 | net | False | 3 | 1.570 MiB/s | 1.541 | 1.606 |
| e1000 | net | True | 3 | 1.565 MiB/s | 1.538 | 1.585 |
| vcpu1-mem256 | cpu | False | 3 | 353.771 Miter/s | 342.718 | 360.655 |
| vcpu1-mem256 | cpu | True | 3 | 350.819 Miter/s | 343.541 | 362.369 |
| vcpu2-mem256 | cpu | False | 3 | 668.667 Miter/s | 612.916 | 706.042 |
| vcpu2-mem256 | cpu | True | 3 | 685.046 Miter/s | 677.837 | 692.662 |
| vcpu2-mem256 | disk | False | 3 | 4.869 MiB/s | 4.499 | 5.123 |
| vcpu2-mem256 | disk | True | 3 | 5.054 MiB/s | 4.810 | 5.359 |
| vcpu2-mem256 | net | False | 3 | 1.687 MiB/s | 1.647 | 1.735 |
| vcpu2-mem256 | net | True | 3 | 1.645 MiB/s | 1.596 | 1.686 |
| vcpu2-mem512 | cpu | False | 3 | 638.625 Miter/s | 565.745 | 683.977 |
| vcpu2-mem512 | cpu | True | 3 | 688.297 Miter/s | 668.307 | 701.817 |
| vcpu4-mem256 | cpu | False | 3 | 1326.533 Miter/s | 1302.360 | 1347.482 |
| vcpu4-mem256 | cpu | True | 3 | 1310.563 Miter/s | 1178.239 | 1378.485 |

## 指标含义

- CPU：每个 vCPU 对应一个普通 pthread，计算整数循环的总 iterations/s；没有自定义驱动。
- 磁盘：64 KiB O_DIRECT 写入→fdatasync→读回校验，循环使用 32 MiB 文件。速率只计已验证写入字节；不等于纯读/写带宽或物理 SSD 性能。
- 网络：单 TCP 连接串行 64 KiB echo，逐块验证。只计单向有效载荷；包含 Guest TCP、QEMU user-net/slirp、WSL loopback server 与往返延迟，不是网卡极限。
- 原始完整 trace.dat/trace.txt 保留在各 run/trace 中；分析窗口为宿主 CLOCK_MONOTONIC 下命令发送至结果接收，包含串口控制开销。
- P50/P95/P99 在 latencies.csv 按运行/TID/metric 分开计算；entry→exit、exit→entry 都是墙钟间隔，含调度等开销。
- common_pid 使用绑定特定本地 TID 的短期 perf tracepoint 采样取得；映射在启动阶段结束，正式测量期间没有该采样器。
- 256/512 MiB 对照使用相同小工作集 CPU 程序；没有压力到内存容量，不能推导内存容量的普遍收益。

## Tracing 开关对照

paired.csv 保存每次成对速率差：100 × (开启/关闭 − 1)。正值表示该次开启组更快。
短时样本数量有限、配置固定顺序与未隔离宿主，差异含调频/缓存/调度噪声，不能直接认定是 tracing 的因果损耗。

| 配置 | 工作负载 | 成对差均值 | 最小 | 最大 |
|---|---|---:|---:|---:|
| ahci | disk | -9.43% | -25.33% | +15.46% |
| e1000 | net | -0.30% | -2.09% | +2.85% |
| vcpu1-mem256 | cpu | -0.81% | -4.02% | +1.12% |
| vcpu2-mem256 | cpu | +2.78% | -1.90% | +10.59% |
| vcpu2-mem256 | disk | +4.03% | -3.52% | +11.00% |
| vcpu2-mem256 | net | -2.42% | -4.97% | +2.38% |
| vcpu2-mem512 | cpu | +8.35% | +1.58% | +18.13% |
| vcpu4-mem256 | cpu | -1.11% | -12.56% | +5.58% |

时序降级运行：[]。采集开始/结束造成的不完整配对保留在每次 summary.json 中。
