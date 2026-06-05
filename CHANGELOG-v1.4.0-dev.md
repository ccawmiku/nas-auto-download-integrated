# NAS Auto Download Integrated v1.4.0-dev

## 目标

`v1.4.0-dev` 是 `v1.3.6` 之后的开发版，先做低风险的结构和界面收敛，不改动抖音 f2 Cookie 的核心格式规则。

## 已调整

- `main` 已合入 `v1.3.6`。
- `dev` 版本号更新为 `v1.4.0-dev`，同步更新：
  - `VERSION`
  - `_integrated/Dockerfile`
  - `_integrated/integrated_server.py`
  - `docker-compose.yml`
  - `README.md`
- 统一首页做轻量控制台化样式优化：
  - 服务卡片状态更清晰。
  - 顶部版本和服务范围使用统一状态标签。
  - 日志长行支持自动换行，避免撑宽页面。
- 新增 `_common/nas_auto_common` 共享层：
  - 集成入口、Pixiv、X、抖音页面共用基础 CSS。
  - 统一按钮、状态标签、表单、卡片、进度、日志等基础控件样式。
  - Docker 集成镜像通过 `PYTHONPATH=/opt/nas-auto` 加载共享包。
- 抖音 worker 减少重复写任务 YAML：
  - 增加任务配置签名。
  - 只有 Cookie、任务、默认下载配置等发生变化时才重写 `like.yaml` / `collection.yaml`。
  - 调度判断加入 `run_pending`，减少重复启动窗口。
- `.gitignore` 增加本地参考和临时目录排除，避免误提交 Cookie 样本和 f2 参考库。

## 后续建议

- 抽出抖音 Cookie 解析/渲染共享模块，减少 `_integrated/integrated_server.py` 和 `_src/douyin-f2-auto-main/douyin_f2_worker.py` 的重复。
- 建立统一的轻量 Web UI 模板，逐步统一 Pixiv、抖音、X、小红书子页面的按钮、状态、日志和配置控件。
