# NAS Auto Download Integrated v1.4.3-dev

## 目标

`v1.4.3-dev` 是 `v1.3.6` 之后的开发版，继续做低风险的结构和界面收敛，不改动抖音 f2 Cookie 的核心格式规则。

## 已调整

- `main` 已合入 `v1.3.6`。
- `dev` 版本号更新为 `v1.4.3-dev`，同步更新：
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
- 集成入口改为侧边栏控制台：
  - 左侧切换总览、小红书、X、Pixiv、抖音。
  - 服务页面通过现有代理在统一工作区中打开，不改变下载 worker 的业务逻辑。
  - Cookie 导入区明确区分“上传 cookies.txt”和“粘贴 Cookie 内容”。
  - Cookie 导入支持预览字段差异，并可多选导入小红书、X、抖音。
- 统一子页面视觉：
  - 删除代理注入的“返回统一主页”顶部条。
  - 小红书页面接入共享 UI 样式，与 X、Pixiv、抖音保持统一控件和配色。
  - 共享 CSS 升级输入框、按钮、状态标签、卡片、表格、日志、焦点态和 hover 态。
- 小红书采集修复和浏览器增强：
  - 修复统一 Cookie 文件导入跳过 `#HttpOnly_` Netscape 行的问题，避免漏掉小红书关键登录 Cookie。
  - Cookie 预览新增关键字段缺失提示，小红书会提示 `a1` / `web_session` 是否齐全。
  - 小红书页面运行间隔输入统一为小时，后端仍兼容秒并保存为秒。
  - 小红书浏览器采集新增可选 CloakBrowser 后端，默认配置优先使用 CloakBrowser，失败时回退 Playwright。
  - CloakBrowser 默认使用轻量 humanize、`zh-CN`、`Asia/Shanghai`、固定 viewport 和持久 profile，减少登录状态丢失，同时不默认开启 geoip 等额外下载/高开销能力。
- 抖音 worker 减少重复写任务 YAML：
  - 增加任务配置签名。
  - 只有 Cookie、任务、默认下载配置等发生变化时才重写 `like.yaml` / `collection.yaml`。
  - 调度判断加入 `run_pending`，减少重复启动窗口。
- `.gitignore` 增加本地参考和临时目录排除，避免误提交 Cookie 样本和 f2 参考库。

## 后续建议

- 抽出抖音 Cookie 解析/渲染共享模块，减少 `_integrated/integrated_server.py` 和 `_src/douyin-f2-auto-main/douyin_f2_worker.py` 的重复。
- 建立统一的轻量 Web UI 模板，逐步统一 Pixiv、抖音、X、小红书子页面的按钮、状态、日志和配置控件。
