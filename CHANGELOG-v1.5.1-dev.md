# v1.5.1-dev

- 小红书自动运行默认关闭，启动后等待手动触发或浏览器脚本提交链接。
- 小红书运行间隔上限从 7 天调整为 30 天，网页继续使用小时输入。
- 新增 `POST /api/xhs/links`，用于接收电脑浏览器 userscript 提交的小红书链接，写入 `/queue/xhs/links.txt` 后触发 worker。
- 小红书第三方下载器 settings 默认不再同步 Cookie，并会移除旧 `cookie` 字段，避免复用无头浏览器或统一导入 Cookie。
- 用户脚本改为向 Docker 批量发送链接，并在 Docker 完整确认接收后才提示发送完成；脚本已随仓库发布在 `tools/userscripts/xhs-docker-queue.user.js`。
