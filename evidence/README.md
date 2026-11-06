# 验证证据的存放范围

本目录保留各阶段已有的验证摘要、统计 CSV、命令记录、诊断日志和失败分析。文件中的日期、机器路径和内核版本描述原来的本地验证环境，不表示 GitHub Actions 重新执行了这些 KVM 或 Guest 测试。

GitHub 代码仓库不包含以下大体积原始数据：`trace.dat`、`trace.txt`、`workload-trace.txt`、`device-trace.log`、`intervals.csv`、`completions.csv`。这些文件仍保存在桌面项目的同名路径，没有删除。上游 Linux trace 参考源码副本也只在本地保留，上游位置见根目录的 `SOURCES.md`。

根目录 `artifacts/` 中的 Guest 镜像和运行包、构建输出以及 `paper-ieee-tc/` 论文交付文件也仅保留在本地。文档提及这些路径时，指的是桌面完整交付目录；克隆代码仓库后可按 `REPRODUCE.md` 从源码构建资产并生成新的测量结果。

`offline/synthetic-report/` 是合成 trace 示例；它不能证明真实 KVM 性能。真实测量与 QEMU/Guest 功能验证的范围以根目录各阶段报告为准。
