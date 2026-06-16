# NAS Auto Download Integrated

NAS 自动下载整合 compose，统一管理：

- 小红书浏览器脚本提交链接 + Docker 端下载（自动采集默认关闭）
- X/Twitter Likes 自动下载
- Pixiv 收藏自动下载
- 抖音点赞/收藏自动下载（f2）
- Instagram 浏览器脚本提交链接 + Docker 端 yt-dlp 队列下载

## 运行方式

统一网页默认使用 14001，小红书 API 保留原来的 13001：

```text
http://NAS_IP:14001
http://NAS_IP:13001
```

启动：

```bash
docker compose up -d
```

默认镜像：

```text
ghcr.io/ccawmiku/nas-auto-download-integrated:v1.7.0-dev
```

每次发布都会同步更新 `docker-compose.yml` 里的镜像版本。NAS 端更新时执行 `docker compose pull && docker compose up -d`，避免复用旧镜像 tag。
仓库根目录的 `VERSION` 是当前集成镜像版本。

## NAS 路径

默认沿用原来的目录：

```text
/volume2/docker/nas-auto-download-integrated/xhs/volumes
/volume2/se-p/小红书
/volume2/docker/nas-auto-download-integrated/xhs/auto/config
/volume2/docker/nas-auto-download-integrated/xhs/auto/queue
/volume2/docker/nas-auto-download-integrated/xhs/auto/state

/volume2/docker/nas-auto-download-integrated/x/config
/volume2/docker/nas-auto-download-integrated/x/state
/volume2/docker/nas-auto-download-integrated/x/downloads-metadata
/volume2/se-p/x-p
/volume1/se-v/x-v

/volume2/docker/nas-auto-download-integrated/pixiv/config
/volume2/docker/nas-auto-download-integrated/pixiv/state
/volume2/se-p/pixiv

/volume2/docker/nas-auto-download-integrated/douyin/config
/volume2/docker/nas-auto-download-integrated/douyin/f2/database
/volume2/qinlong-debian/F2DL

/volume2/docker/nas-auto-download-integrated/instagram/config
/volume2/docker/nas-auto-download-integrated/instagram/queue
/volume2/docker/nas-auto-download-integrated/instagram/state
/volume2/se-p/instagram
```

需要调整时直接改 `docker-compose.yml`。

## 统一网页

打开 `http://NAS_IP:14001` 后：

- 统一首页回到轻量 Python 控制台，不再引入 React/Vue/shadcn-ui，也不需要 Node 构建阶段
- 首页总览显示小红书、X、Pixiv、抖音、Instagram 的服务状态、运行状态、当前任务和下次运行倒计时
- 服务入口只保留在侧边栏；子服务启动中时统一首页仍会先打开
- 统一 Cookie 导入、从文件上传 `cookies.txt` 导入 Cookie 已移除
- 小红书自动运行、无头浏览器采集、CloakBrowser 和旧统一 Cookie 导入已经完全移除
- 小红书浏览器脚本可以把作品链接提交到 `http://NAS_IP:14001/api/xhs/links`，Docker 写入 `/queue/xhs/links.txt` 后才返回确认；网页确认完成后可以直接关闭
- 小红书管理页可以单独粘贴 Cookie Header，并写入 JoeanAmier/XHS-Downloader 2.7 的 `/xhs-volume/settings.json` 里的 `cookie` 字段
- 小红书管理页会显示浏览器脚本发来的队列、单独错误列表、worker 日志和 `xhs-api` 日志；compose 会把 `xhs-api` 输出追加到 `/app/Volume/xhs-api.log`
- 小红书管理页提供红色“清空所有队列”按钮，会清理待处理/待重试/失败项并清空队列文件
- 小红书遇到 `ReadTimeout`、`RemoteProtocolError`、`peer closed`、`网络异常` 等临时网络错误时会先标记为待重试，默认几分钟后自动重试
- X 管理页支持单独粘贴 Cookie Header 保存，不再通过统一首页或文件上传导入
- X 管理页会单独列出 `No video could be found in this tweet` 的失败链接，方便手动下载后删除记录
- Pixiv 页面内可以生成登录链接、粘贴 callback/code、换取 refresh-token
- 抖音页面会显示当前 f2 版本、PyPI 最新版本和检查时间，可手动触发版本检查
- 抖音页面支持单独粘贴 `app.yaml` 里的 `cookie:` 段并直接保存，不依赖统一首页导入
- 抖音日志会自动刷新，长行会换行，Cookie 和 URL 参数会做脱敏/截断
- 抖音任务不再使用固定单任务超时；每个点赞/收藏项目按 f2 输出里的作品 ID 统计，连续 10 个作品都只有 `[跳过]`、没有 `[完成]` 时停止当前项目
- 抖音页面会检查关键字段和参考 `app.yaml` 的 64 个字段，字段不满会直接提示风险
- 抖音页面支持手动停止当前运行中的任务，停止后不会继续后续 job
- 抖音运行目录会生成本地 `conf/conf.yaml` 并默认关闭 f2 的 Bark 推送，避免未配置 Bark 时额外报 405 噪音
- Instagram 推荐通过 `tools/userscripts/instagram-docker-queue.user.js` 在电脑浏览器采集已加载的 post/reel 链接，提交到 `http://NAS_IP:14001/api/instagram/links`；Docker 端默认不使用主账号 Cookie，直接用 `yt-dlp` 队列下载公开可访问内容
- 统一首页使用侧边栏切换子页面，子页面不再额外注入返回条

## 小红书浏览器脚本队列

小红书当前默认不再由 NAS 无头浏览器主动打开账号页面。推荐流程是：

```text
电脑浏览器 userscript 采集当前作品/页面链接（仓库脚本：tools/userscripts/xhs-docker-queue.user.js）
  -> POST http://NAS_IP:14001/api/xhs/links
  -> Docker 写入 /queue/xhs/links.txt 并触发小红书 worker
  -> worker 按队列一个一个调用 xhs-api 下载到 /xhs
```

接口接受 JSON：

```json
{"urls":["https://www.xiaohongshu.com/explore/xxx"]}
```

返回里的 `accepted` 是本次新入队数量，`skipped` 是已经在队列中的数量；只有有效链接完整写入或确认已存在时，浏览器脚本才提示发送完成。

小红书下载器 Cookie 在小红书页面单独填写，保存位置是：

```text
/volume2/docker/nas-auto-download-integrated/xhs/volumes/settings.json
```

该 Cookie 只给 JoeanAmier/XHS-Downloader 2.7 的 API 下载使用，不再和 NAS 无头浏览器或统一 Cookie 导入共用。

## 抖音 f2 迁移

抖音集成使用 `f2==0.0.1.7`，默认跑点赞和收藏两个任务。f2 自己的数据库继续沿用：

```text
/volume2/docker/nas-auto-download-integrated/douyin/f2/database/douyin_users.db
/volume2/docker/nas-auto-download-integrated/douyin/f2/database/douyin_videos.db
```

如果之前在青龙面板里已经跑过 f2，把原来的 `douyin_users.db` 放到上面的 `database` 目录即可延续点赞/收藏记录；有 `douyin_videos.db` 也可以一起放进去，没有也能运行，f2 需要时会自行创建。抖音 Cookie 会以 UTF-8 写入 `/config/douyin/douyin_cookie.txt`，在抖音页面直接粘贴 `app.yaml` 里的 `cookie:` 段单独保存。保存时会按本地参考 `app.yaml` 的字段顺序重新拼接，只保留抖音实际需要的项，并额外丢弃非 ASCII 值，避免 `httpx` 在构造 Cookie 请求头时因异常字符报错。`douyin_cookie.txt`、`like.yaml`、`collection.yaml` 都会严格按本地参考 `app.yaml` 的原始分组、换行、缩进和末行无分号规则输出；抖音页保存会立即同步重写 `like.yaml`、`collection.yaml`，并默认写入 `/F2DL`、`mode: like/collection`、`folderize: true`、`cover: false` 和 `{create}-{nickname}-{aweme_id}` 命名。

下载目录挂载为 `/volume2/qinlong-debian/F2DL:/F2DL`。f2 会按配置里的 `mode` 自动保存到：

```text
/volume2/qinlong-debian/F2DL/douyin/like/昵称/作品文件夹
/volume2/qinlong-debian/F2DL/douyin/collection/昵称/作品文件夹
```

## 自动停止与重试

- X 不再使用全局浏览器锁，只保留项目自身的运行锁，避免重复启动同一个 X 任务
- X 的“连续已下载停止”按数据库 `done` 状态判断，迁移后不会因为旧文件路径变化而一直下翻
- 小红书临时网络错误默认进入待重试队列，worker 会自动在稍后重跑
- Pixiv OAuth/API/图片下载带网络重试；无 refresh-token 时不会自动运行下载任务，只保留网页等待配置

## 停旧容器后迁移

确认新镜像已拉取后，可以停掉旧的 worker。旧 `xhs-api` 也需要停掉，让本 compose 用同样的配置重新管理：

```bash
docker stop xhs-auto-worker x-auto-downloader pixiv-auto-downloader
docker stop xhs-api
```

然后启动整合 compose：

```bash
docker compose up -d
```

## 本地构建

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```
