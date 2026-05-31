# NAS Auto Download 集成版

这个目录把三个现有 Docker 项目放到同一个 `docker-compose.yml` 里运行，并统一了凭据导入方式。

## 服务与端口

- 小红书 API: `13001`
- 小红书 Worker Web UI: `13003`
- X Worker Web UI: `13004`
- Pixiv Worker Web UI: `13005`

这里按现有 NAS 目录保留端口规划：小红书继续用 `13003`，X 用 `13004`，Pixiv 用 `13005`。

## 目录布局

默认沿用这些目录：

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

## 一次性导入

推荐把浏览器导出的文件先放到一个临时目录，然后一次性导入到统一的 `secrets/`：

```bash
python tools/import_credentials.py \
  --xhs /path/to/xhs-cookies.txt \
  --x /path/to/x-cookies.txt \
  --pixiv-token /path/to/pixiv_refresh_token.txt
```

如果一个目录里已经放好了导出的文件，也可以让脚本按文件名和内容自动识别：

```bash
python tools/import_credentials.py \
  --bundle /path/to/exported-credentials
```

导入后会写入：

```text
/volume2/docker/xhs-downloader/auto/config/xhs_cookie.txt
/volume2/docker/x-auto-download/config/x_cookies.txt
/volume2/docker/pixiv-auto-download/config/pixiv_refresh_token.txt
```

XHS 和 X 都支持 Netscape `cookies.txt`，也兼容 Cookie header 和常见浏览器扩展导出的 JSON。Pixiv 这个项目使用的是 Pixiv API refresh-token，不是浏览器 Cookie；这里已经内置 gallery-dl 同款 Pixiv OAuth 转换流程，用它生成 token 后会写入 `secrets/pixiv_refresh_token.txt`。

## Pixiv OAuth 转换

在 NAS 上推荐用这个一次性工具服务：

```bash
docker compose run --rm pixiv-oauth
```

它会打印 Pixiv 登录链接。用浏览器打开并登录后，从开发者工具 Network 里复制最后的 `callback?state=...&code=...` URL，粘贴回终端，脚本会把 refresh-token 保存到：

```text
/volume2/docker/pixiv-auto-download/config/pixiv_refresh_token.txt
```

也可以在当前机器上分两步专门测试：

```bash
python tools/pixiv_gallerydl_oauth.py --start --state-file pixiv_oauth_state.json
python tools/pixiv_gallerydl_oauth.py --finish "粘贴 callback URL 或 code" --state-file pixiv_oauth_state.json --output pixiv_refresh_token.txt
```

注意 Pixiv 的 `code` 有效期很短，通常需要在登录后马上复制并执行 `--finish`。

## 手动导入

三套服务也支持两种常用方式：

- Web UI 粘贴保存：适合临时更新。
- `secrets/` 文件注入：适合 NAS 长期维护和备份。

文件方式：

```text
/volume2/docker/xhs-downloader/auto/config/xhs_cookie.txt       小红书 Cookie
/volume2/docker/x-auto-download/config/x_cookies.txt            X Cookie
/volume2/docker/pixiv-auto-download/config/pixiv_refresh_token.txt Pixiv refresh-token
```

Web UI 写入的位置仍在各自 `/config` 或 `/state` 下，不会改写 `secrets/`。优先级大致是：Web UI 保存值或环境变量优先，其次是 `secrets/` 文件，最后是配置默认值。

## 启动

```bash
cp .env.example .env
docker compose up -d
```

首次启动会自动把每个项目的 `config.example.json` 复制为对应的 `/config/config.json`。之后可以直接编辑：

```text
/volume2/docker/xhs-downloader/auto/config/config.json
/volume2/docker/x-auto-download/config/config.json
/volume2/docker/pixiv-auto-download/config/config.json
```

## 需要特别改的配置

小红书需要在 `/volume2/docker/xhs-downloader/auto/config/config.json` 里把 `browser.targets[0].url` 改成自己的点赞页。

X 如果不能从 `twid` 自动识别账号，可以在 `/volume2/docker/x-auto-download/config/config.json` 里设置 `browser.screen_name` 或 `browser.likes_url`。

Pixiv 可以通过 `docker compose run --rm pixiv-oauth` 生成 refresh-token，Web UI 里也可以测试 Token。

## 镜像

GitHub Actions 会在推送 tag 时构建这三个镜像：

```text
ghcr.io/ccawmiku/nas-auto-download-integrated-xhs-auto-worker:v1.0.0
ghcr.io/ccawmiku/nas-auto-download-integrated-x-auto-worker:v1.0.0
ghcr.io/ccawmiku/nas-auto-download-integrated-pixiv-auto-worker:v1.0.0
```

如果要在源码目录本地构建，可以使用：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```
