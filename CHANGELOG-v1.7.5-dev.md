# v1.7.5-dev

- 恢复集成镜像运行时依赖 `gallery-dl`，修复 Pixiv worker 启动时报 `No module named 'gallery_dl'`。
- 恢复集成镜像运行时依赖 `yt-dlp`，修复 X 视频下载时报 `No such file or directory: 'yt-dlp'`。
- 增加依赖回归测试，避免后续清理外站实验代码时误删 X/Pixiv 仍需要的工具。
