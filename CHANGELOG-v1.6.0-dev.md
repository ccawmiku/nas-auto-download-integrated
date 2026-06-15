# v1.6.0-dev

- 移除集成首页的 React/Vite/shadcn-ui 前端工程，镜像构建回到纯 Python 控制台，不再需要 Node 构建阶段。
- 移除 CloakBrowser 依赖和小红书 NAS 端无头浏览器自动采集逻辑。
- 小红书 worker 改为队列下载模式：只接收网页脚本或页面粘贴提交的链接，写入 SQLite 后按队列串行提交到 `xhs-api`。
- 小红书管理页新增 JoeanAmier/XHS-Downloader 2.7 `settings.json` Cookie 保存入口，并显示队列、worker 日志和 `xhs-api` 日志。
- `docker-compose.yml` 将 `xhs-api` 日志追加到 `/app/Volume/xhs-api.log`，方便集成页面读取。
- 统一 Cookie 导入不再处理小红书，只保留 X 和抖音。
- X 管理页新增 “No video could be found in this tweet” 失败链接清单，并支持手动删除记录。
- 各服务网页日志保留上限提高到 5000 行。
