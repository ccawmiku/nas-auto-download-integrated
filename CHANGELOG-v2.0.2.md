# CHANGELOG v2.0.2

## Fixed

- 限制 X Likes 单次 Chromium 会话的滚动次数，旧配置 `max_scrolls: 0` 现在使用安全上限 20 次。
- X Worker 拦截浏览器不需要的图片、媒体和字体资源，下载仍由 Worker 使用独立下载器完成。
- Chromium 增加共享内存、缓存、扩展和 V8 堆的资源限制。
- 统一使用异步上下文清理 Playwright browser/context，异常退出也会关闭 Chromium。
