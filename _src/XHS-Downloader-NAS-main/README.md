# XHS Liked Notes Auto Downloader for NAS

基于 [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader) 的 NAS 自动化辅助工具。

它会在 NAS 端定时打开小红书点赞页，提取新点赞作品链接，并调用本地 XHS-Downloader API 下载。适合群晖 Container Manager / Docker Compose 使用。

## 功能

- 自动同步“小红书点赞作品”
- 支持网页端填写 Cookie，不需要写进 compose
- 支持网页端查看状态、日志、失败原因
- 支持网页端修改运行间隔
- 使用 SQLite 记录已发现、已下载、失败、停止标记，避免重复下载
- 遇到指定标题时停止继续向下同步，停止作品本身不下载
- 推送到 GitHub 后由 GitHub Actions 自动构建 worker 镜像，镜像 tag 带版本号

默认停止标题：

```text
数学界最美味的一天
```

## 文件说明

```text
nas-auto/
├── docker-compose.yml      # 使用 GHCR 镜像的双容器 compose
├── config.example.json     # worker 配置模板
├── xhs_auto_worker.py      # 自动同步 worker + 状态网页
├── liked_extractor.js      # 页面数据提取脚本
├── Dockerfile           # worker 镜像构建文件
├── VERSION              # worker 镜像默认版本 tag
├── .github/workflows/   # GitHub Actions 自动构建
├── README.md
└── .gitignore
```

## 端口

- `13001`：XHS-Downloader API
- `13003`：状态网页

状态网页地址：

```text
http://你的NAS地址:13003
```

例如：

```text
http://192.168.1.20:13003
```

## 部署

下面路径按群晖示例写。你可以按自己的 NAS 路径调整。

### 1. 放置文件

把整个 `nas-auto` 文件夹放到：

```text
/volume1/docker/xhs-downloader/nas-auto
```

创建运行目录：

```bash
mkdir -p /volume1/docker/xhs-downloader/auto/config
mkdir -p /volume1/docker/xhs-downloader/auto/queue
mkdir -p /volume1/docker/xhs-downloader/auto/state
mkdir -p /volume1/docker/xhs-downloader/volumes
```

复制配置：

```bash
cp /volume1/docker/xhs-downloader/nas-auto/config.example.json \
   /volume1/docker/xhs-downloader/auto/config/config.json
```

### 2. 修改配置

编辑：

```text
/volume1/docker/xhs-downloader/auto/config/config.json
```

找到：

```json
"url": "https://www.xiaohongshu.com/user/profile/YOUR_USER_ID?tab=liked"
```

把 `YOUR_USER_ID` 改成你自己的小红书用户 ID。

点赞页需要带：

```text
?tab=liked
```

如果你漏写，worker 也会自动补上。

### 3. 修改下载目录

打开：

```text
/volume1/docker/xhs-downloader/nas-auto/docker-compose.yml
```

默认下载目录映射是：

```yaml
- /volume1/se/小红书:/xhs
```

如果你的下载目录不同，改成你的实际路径。

### 4. 启动

进入项目目录：

```bash
cd /volume1/docker/xhs-downloader/nas-auto
```

启动两个容器：

```bash
docker compose up -d
```

查看 worker 日志：

```bash
docker logs -f xhs-auto-worker
```

## 使用

### 1. 打开状态网页

```text
http://你的NAS地址:13003
```

例如：

```text
http://192.168.1.20:13003
```

### 2. 保存 Cookie

在“Cookie 设置”里粘贴小红书 Cookie，点击“保存设置”。

Cookie 会保存到：

```text
/volume1/docker/xhs-downloader/auto/state/secrets.json
```

这个文件不应该提交到 GitHub。

worker 每次运行开始时，会把 Cookie 同步到 XHS-Downloader 的：

```text
/volume1/docker/xhs-downloader/volumes/settings.json
```

只会改 `cookie` 和 `user_agent`，不会改下载目录、命名规则、图片格式等其它配置。

### 3. 手动运行一次

在状态网页点击：

```text
立即运行一次
```

### 4. 修改运行间隔

在状态网页的“运行间隔（秒）”里填写数字。

常用值：

- `1800`：30 分钟
- `3600`：1 小时
- `18000`：5 小时

保存后会自动重新计算下次运行时间，不需要重启容器。

## 工作方式

每次运行时：

1. 读取网页保存的 Cookie
2. 同步 Cookie 到 XHS-Downloader 的 `settings.json`
3. 打开你的个人主页点赞页
4. 滚动加载点赞作品
5. 从页面状态中提取作品 ID、标题、作者、`xsec_token`
6. 遇到停止标题就停止
7. 将新作品提交给 `http://你的NAS地址:13001/xhs/detail`
8. 将结果写入 SQLite 数据库

数据库路径：

```text
/volume1/docker/xhs-downloader/auto/state/xhs_auto.sqlite3
```

## 重要配置

`config.json` 中常用字段：

```json
{
  "api_url": "http://192.168.1.20:13001/xhs/detail",
  "run_interval_seconds": 1800,
  "database": "/state/xhs_auto.sqlite3",
  "secrets_path": "/state/secrets.json",
  "stop_marker": {
    "enabled": true,
    "title": "数学界最美味的一天",
    "match": "exact"
  },
  "browser": {
    "scroll_count": 40,
    "targets": [
      {
        "kind": "profile_liked",
        "url": "https://www.xiaohongshu.com/user/profile/YOUR_USER_ID?tab=liked"
      }
    ]
  }
}
```

如果你的 NAS 地址不是 `192.168.1.20`，需要把 `api_url` 改成你的地址。

## 更新代码

现在 worker 镜像由 GitHub Actions 构建。更新代码后：

1. 提交并 push 到 GitHub
2. 等待 `Build worker Docker image` Actions 完成
3. NAS 上执行：

```bash
cd /volume1/docker/xhs-downloader/nas-auto
docker compose pull
docker compose up -d
```

默认镜像是 `ghcr.io/ccawmiku/xhs-downloader-nas-worker:v1.3.1`，也可以通过 `.env` 里的 `XHS_AUTO_WORKER_IMAGE` 和 `XHS_AUTO_WORKER_VERSION` 覆盖。

## 排错

### 状态网页打不开

检查：

- `xhs-auto-worker` 是否运行
- compose 是否映射了 `13003:8080`
- NAS 防火墙是否放行 `13003`
- 地址是否写对

### 没有下载请求进入 xhs-api

检查 worker 日志：

```bash
docker logs -f xhs-auto-worker
```

常见原因：

- Cookie 没保存或已失效
- `config.json` 里的用户 ID 不对
- 目标地址不是点赞页
- 页面出现登录验证或风控
- Playwright 安装失败

### 检查 Playwright

```bash
docker exec -it xhs-auto-worker python -c "from playwright.async_api import async_playwright; print('ok')"
```

正常应输出：

```text
ok
```

### xhs-api 是否正常

浏览器打开：

```text
http://你的NAS地址:13001/docs
```

如果打不开，先修复 XHS-Downloader API 容器。

## 风险与合规

请只保存自己有权保存的内容，不要公开分发他人作品。

自动化访问可能触发平台风控。低频、小量、个人备份用途风险相对较低，但并不等于没有风险。出现验证码、403、Cookie 频繁失效、失败数量异常增加时，建议暂停使用。

本项目不包含破解、绕过登录、绕过风控等功能。

## 致谢

下载能力来自：

[JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)


## GitHub Actions 自动构建镜像

提交并 push 到 `main` / `master` 或推送 `v*` tag 后，`.github/workflows/docker-image.yml` 会自动构建 worker 镜像并推送到 GHCR：

```text
ghcr.io/ccawmiku/xhs-downloader-nas-worker:v1.3.1
```

如果 GHCR package 是 private，NAS 上需要先 `docker login ghcr.io`。如果改成 public package，NAS 可以直接 pull。
