# NAS Auto Download Integrated v1.5.0-dev

## 目标

`v1.5.0-dev` 是一次偏激进的统一网页改造：把集成入口从 Python 拼接 HTML 迁移到 React + shadcn 风格控制台，同时保留现有 worker、代理和下载逻辑。

## 已调整

- `main` 已快进合入 `v1.4.3-dev`。
- `dev` 版本号更新为 `v1.5.0-dev`，同步更新：
  - `VERSION`
  - `_integrated/Dockerfile`
  - `_integrated/integrated_server.py`
  - `docker-compose.yml`
  - `README.md`
- 新增 `_frontend/integrated` 前端工程：
  - Vite + React + TypeScript。
  - Tailwind + shadcn-ui 风格基础组件。
  - lucide 图标。
  - 统一侧边栏、服务状态、Cookie 导入、差异预览、日志面板和子服务工作区。
  - 小红书、X、Pixiv、抖音均增加 React 原生状态面板、日志区和快捷操作按钮。
- Docker 改为多阶段构建：
  - Node 只用于构建 React 静态资源。
  - 最终 Playwright Python 镜像只拷贝 `/opt/nas-auto/web`，不保留 Node 运行时。
- 集成服务新增静态资源托管：
  - 有 React 构建产物时优先返回 React 首页。
  - 没有构建产物时保留原 Python fallback 首页，便于本地测试和排障。
- Cookie 导入新增 JSON API：
  - `/api/cookie-preview` 保持用于差异预览。
  - 新增 `/api/cookie-import`，React 页面可直接导入并返回 JSON 结果。
- 子服务原页面保留为“高级设置” iframe：
  - 复杂表单和特殊流程仍可直接使用。
  - React 原生页面先承接状态、日志、运行/停止/重载等高频操作。

## 后续建议

- 逐个将小红书、X、Pixiv、抖音的内部页面 API 标准化，再从 iframe 迁移到 React 原生视图。
- 给 React 控制台增加每个服务的快捷操作，例如运行、停止、保存设置、Cookie 测试等。
- 用浏览器截图建立 UI 回归检查，避免后续样式大改时出现移动端溢出或 iframe 高度问题。
