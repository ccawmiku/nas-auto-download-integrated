# NAS Auto Download Integrated

单容器版 NAS 自动下载器，统一管理：

- 小红书点赞自动下载
- X/Twitter Likes 自动下载
- Pixiv 收藏自动下载

## 运行方式

默认只暴露一个端口：

```text
http://NAS_IP:14001
```

启动：

```bash
cp .env.example .env
docker compose up -d
```

默认镜像：

```text
ghcr.io/ccawmiku/nas-auto-download-integrated:v1.1.1
```

## NAS 路径

默认沿用原来的目录：

```text
/volume2/docker/xhs-downloader/volumes
/volume2/se-p/小红书
/volume2/docker/xhs-downloader/auto/config
/volume2/docker/xhs-downloader/auto/queue
/volume2/docker/xhs-downloader/auto/state

/volume2/docker/x-auto-download/config
/volume2/docker/x-auto-download/state
/volume2/docker/x-auto-download/downloads-metadata
/volume2/se-p/x-p
/volume1/se-v/x-v

/volume2/docker/pixiv-auto-download/config
/volume2/docker/pixiv-auto-download/state
/volume2/se-p/pixiv
```

需要调整时改 `.env`。

## 统一网页

打开 `http://NAS_IP:14001` 后：

- 首页可以进入小红书、X、Pixiv 三个原有管理页面
- 首页可以粘贴浏览器插件导出的一整份全站 Cookie header
- 首页也可以上传 `cookies.txt`，只解析内容，不保存原始上传文件
- 导入器会自动拆出小红书和 X 所需 Cookie
- Pixiv 页面内可以生成登录链接、粘贴 callback/code、换取 refresh-token
- 子页面顶部会显示“返回统一主页”

## 浏览器性能保护

小红书和 X 都会使用 Playwright 无头浏览器。单容器内置全局浏览器锁：

- 同一时间只允许一个无头浏览器采集任务运行
- 另一个任务会等待，默认最长等待 7200 秒
- 可通过 `BROWSER_LOCK_WAIT_SECONDS` 调整
- X 的“连续已下载停止”按数据库 `done` 状态判断，迁移到单容器后不会因为旧文件路径变化而一直下翻

## 停旧容器后迁移

确认新镜像已拉取后，可以停掉旧的：

```bash
docker stop xhs-auto-worker x-auto-downloader pixiv-auto-downloader
docker stop xhs-api
```

然后启动单容器：

```bash
docker compose up -d
```

## 本地构建

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```
