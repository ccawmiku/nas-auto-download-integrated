# NAS Auto Download Integrated

NAS 自动下载整合 compose，统一管理：

- 小红书点赞自动下载
- X/Twitter Likes 自动下载
- Pixiv 收藏自动下载
- 抖音点赞/收藏自动下载（f2）

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
ghcr.io/ccawmiku/nas-auto-download-integrated:v1.3.5
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
```

需要调整时直接改 `docker-compose.yml`。

## 统一网页

打开 `http://NAS_IP:14001` 后：

- 首页可以进入小红书、X、Pixiv、抖音四个管理页面
- 首页会显示各子服务是否就绪；子服务启动中时统一首页仍会先打开
- 首页可以粘贴浏览器插件导出的一整份全站 Cookie header
- 首页也可以上传 `cookies.txt`，只解析内容，不保存原始上传文件
- 导入器会自动拆出小红书、X 和抖音所需 Cookie
- Pixiv 页面内可以生成登录链接、粘贴 callback/code、换取 refresh-token
- 抖音页面会显示当前 f2 版本、PyPI 最新版本和检查时间，可手动触发版本检查
- 抖音页面支持单独粘贴 `app.yaml` 里的 `cookie:` 段并直接保存，不依赖统一首页导入
- 抖音日志会自动刷新，长行会换行，Cookie 和 URL 参数会做脱敏/截断
- 抖音任务默认单任务 3 分钟超时，超过后会终止并记为 `timeout`
- 抖音页面会检查关键字段和参考 `app.yaml` 的 64 个字段，字段不满会直接提示风险
- 抖音页面支持手动停止当前运行中的任务，停止后不会继续后续 job
- 抖音运行目录会生成本地 `conf/conf.yaml` 并默认关闭 f2 的 Bark 推送，避免未配置 Bark 时额外报 405 噪音
- 子页面顶部会显示“返回统一主页”

## 抖音 f2 迁移

抖音集成使用 `f2==0.0.1.7`，默认跑点赞和收藏两个任务。f2 自己的数据库继续沿用：

```text
/volume2/docker/nas-auto-download-integrated/douyin/f2/database/douyin_users.db
/volume2/docker/nas-auto-download-integrated/douyin/f2/database/douyin_videos.db
```

如果之前在青龙面板里已经跑过 f2，把原来的 `douyin_users.db` 放到上面的 `database` 目录即可延续点赞/收藏记录；有 `douyin_videos.db` 也可以一起放进去，没有也能运行，f2 需要时会自行创建。抖音 Cookie 会以 UTF-8 写入 `/config/douyin/douyin_cookie.txt`，既支持统一主页从 `cookies.txt` 拆分导入，也支持在抖音页面直接粘贴 `app.yaml` 里的 `cookie:` 段单独保存。保存时会按本地参考 `app.yaml` 的字段和顺序重新拼接，只保留抖音实际需要的项，并额外丢弃非 ASCII 值，避免 `httpx` 在构造 Cookie 请求头时因异常字符报错。`douyin_cookie.txt` 本身会按参考 `app.yaml` 的 `cookie:` 多行段保存，统一首页导入和抖音页单独保存都会立即同步重写 `like.yaml`、`collection.yaml`，任务 YAML 继续按同样的换行和缩进格式输出，并默认写入 `/F2DL`、`mode: like/collection`、`folderize: true`、`cover: false` 和 `{create}-{nickname}-{aweme_id}` 命名。

下载目录挂载为 `/volume2/qinlong-debian/F2DL:/F2DL`。f2 会按配置里的 `mode` 自动保存到：

```text
/volume2/qinlong-debian/F2DL/douyin/like/昵称/作品文件夹
/volume2/qinlong-debian/F2DL/douyin/collection/昵称/作品文件夹
```

## 浏览器性能保护

小红书和 X 都会使用 Playwright 无头浏览器。整合 worker 容器内置全局浏览器锁：

- 同一时间只允许一个无头浏览器采集任务运行
- 另一个任务会等待，默认最长等待 7200 秒
- X 的“连续已下载停止”按数据库 `done` 状态判断，迁移后不会因为旧文件路径变化而一直下翻
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
