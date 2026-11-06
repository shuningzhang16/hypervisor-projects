# 首次完整运行的失败与修复

首次 kvm-split 的正常请求、并发、采样、reset、重载、超时和打开 FD 移除均已完成。
再次 device_add 后，脚本固定等待 1 秒便运行 smoke，Guest 此时仍在异步初始化 PCI transport，
尚未创建设备节点，因此客户端报 one lab misc device。原始 failure.txt、serial.log、QMP、trace 与 console 均保留。

最小修复：用 Guest 端 await-device 命令在最多 15 秒内等待实际字符设备节点，然后再执行相同 smoke。
没有放宽 smoke 断言、驱动协议检查或 reset 行为。新隔离 Guest 中 split/packed 完整流程通过，旧失败结果未覆盖。
