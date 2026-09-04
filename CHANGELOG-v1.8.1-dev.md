# CHANGELOG v1.8.1-dev

## 修复与优化

1. **解决 Docker 容器僵尸进程（`<defunct>`）堆积问题**：
   - 镜像集成轻量级 init 工具 `tini`，设置 `ENTRYPOINT ["/usr/bin/tini", "--"]`，作为 PID 1 自动收割子进程并正确分发系统信号；
   - 在 `integrated_server.py` 中增加孤儿僵尸进程后台自动收割机制（`os.waitpid(-1, os.WNOHANG)`）与 `SIGCHLD` 信号绑定，双重保险彻底杜绝 Playwright 无头浏览器（`headless_shell`）及命令行工具退出后残留僵尸进程。

2. **解决 `douyin_f2_worker` 高频 CPU 与磁盘 I/O 损耗**：
   - 增加配置文件 `mtime` 状态缓存，避免每次轮询无意义地重新读取配置与重构字典；
   - 在写入 `conf.yaml` 前进行内容一致性比对，避免在未发生变更时每 5 秒覆写磁盘；
   - 调度轮询等待时间调整为 10 秒。

3. **版本升级**：
   - 升级版本至 `v1.8.1-dev`。
