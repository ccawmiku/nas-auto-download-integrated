# v1.6.2-dev

- 小红书下载器图片格式默认改为 `AUTO`，避免强制 `imageView2/format/png` 导致部分 CDN 图片返回 400。
- 小红书页面新增图片格式选择，并会同步写入 XHS-Downloader `settings.json`。
- 小红书队列 worker 会读取本次 `xhs-api` 调用新增日志；如果接口返回 200 但日志里出现 `下载失败`、`网络异常` 或 `HTTPStatusError`，会把该作品标记为失败，避免误判完成。
