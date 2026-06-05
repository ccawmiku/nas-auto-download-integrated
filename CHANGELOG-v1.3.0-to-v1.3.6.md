# NAS Auto Download Integrated 变更报告

本文汇总 `v1.3.0` 到 `v1.3.6` 的抖音集成相关演进，便于排查回归、对外说明和后续继续迭代。

## v1.3.0

- 抖音 `f2` 集成首次接入统一项目，新增抖音管理页与点赞、收藏两个任务。
- 容器启动后不再在 5 秒内立即执行抖音抓取，改为等待下一次计划时间再运行。
- 点赞、收藏和手动单次运行共用同一运行门禁，避免重复并发启动。
- 抖音页面新增单独 Cookie 导入入口，支持直接粘贴 `app.yaml` 里的 `cookie:` 段。
- 统一首页的 Cookie 导入增加抖音识别，能从 `cookies.txt` 或粘贴文本中拆出抖音 Cookie。
- 抖音日志页面支持自动刷新、长行换行，并对 Cookie 和 URL 参数做脱敏/截断。
- 同步更新版本号与容器镜像版本引用。

## v1.3.1

- 新增运行时 `conf/conf.yaml` 覆盖逻辑，默认关闭 `f2` 的 Bark 推送。
- 解决任务本身成功，但因 `https://api.day.app/` 返回 `405` 导致日志出现额外错误噪音的问题。
- 保留 `f2` 主配置的其他参数，只对 Bark 开关做最小覆盖。

## v1.3.2

- 抖音页面新增 Cookie 风险提示。
- 页面会检查关键字段是否齐全，并统计参考 `app.yaml` 的字段覆盖数。
- 新增风险等级区分：
  - `64/64` 且关键字段完整时显示“正常”
  - 关键字段缺失时显示“高风险”
  - 关键字段齐全但参考字段不满时显示“有风险”
- 抖音页面新增手动停止按钮，运行中可以主动终止当前任务，并阻止继续后续 job。
- 保持 Bark 抑制逻辑，避免恢复旧噪音。

## v1.3.3

- 开始修正抖音 Cookie 到任务 YAML 的格式问题。
- `like.yaml` 和 `collection.yaml` 不再直接依赖通用 `yaml.safe_dump` 输出 `cookie:` 单行标量。
- 改为手工渲染 `cookie:` 多行段，初步对齐参考 `app.yaml` 的缩进和多行结构。
- 这一步修复了“导入后 YAML 仍然过于扁平”的一部分问题，但还没有完全匹配参考 `app.yaml` 的真实分组。

## v1.3.4

- 把多行块保存逻辑从任务 YAML 扩展到 `/config/douyin/douyin_cookie.txt`。
- 统一首页导入和抖音页单独保存后，`douyin_cookie.txt` 不再保存为单行 Cookie header，而是保存为 `cookie:` 多行段。
- `like.yaml` 和 `collection.yaml` 继续沿用多行 `cookie:` 输出，三份文件的格式方向首次统一。
- 这一版已经解决“源 Cookie 文件还是单行”的问题，但任务 YAML 还不会在导入后立即自动刷新。

## v1.3.5

- 统一首页导入或抖音页单独保存后，会立刻同步重写 `like.yaml` 和 `collection.yaml`。
- 不再需要等待下一次运行或重新进入任务流程，三个文件会在 Cookie 更新后同步刷新。
- 抖音 worker 在初始化目录、保存配置、保存 Cookie 后都会重建任务 YAML，减少旧配置残留。
- 统一首页导入也会读取抖音配置并生成对应任务 YAML，补齐了入口之间行为不一致的问题。

## v1.3.6

- 严格按本地参考 `app.yaml` 的真实 `cookie:` 分组规则输出，不再使用“每个分号换行”的简化策略。
- 参考布局已固化为固定分组模式，例如：
  - `my_rd; volume_info; WallpaperGuide` 同行
  - `is_staff_user; has_biz_token; sid_ucp_v1` 同行
  - `enter_pc_once; hevc_supported; home_can_add_dy_2_desktop; stream_recommend_feed_params` 同行
- 最后一行严格保持“无结尾分号”，与参考 `app.yaml` 一致。
- 该规则同时应用到：
  - `/config/douyin/douyin_cookie.txt`
  - `/config/douyin/f2/like.yaml`
  - `/config/douyin/f2/collection.yaml`
- 新增测试覆盖：
  - 统一导入后源 Cookie 文件的精确文本布局
  - 统一导入后两个任务 YAML 的精确文本布局
  - 多字段同行分组的渲染结果
  - 末行无分号时的 YAML 解析结果

## 总体演进总结

- `v1.3.0` 到 `v1.3.2` 主要解决“能运行、能看见状态、能停止、能看风险”。
- `v1.3.3` 到 `v1.3.6` 主要解决“Cookie 导入后格式必须与参考 `app.yaml` 真正一致”。
- 当前抖音 Cookie 相关链路已经统一为：
  - 导入时按参考字段顺序筛选
  - 保存时按参考 `app.yaml` 原始分组和缩进输出
  - 保存后自动同步重建 `like.yaml` 和 `collection.yaml`

## 当前最新版

- 最新版：`v1.3.6`
- 目标：保证抖音 Cookie 从导入、保存到任务 YAML 全链路都严格贴合本地参考 `app.yaml`
