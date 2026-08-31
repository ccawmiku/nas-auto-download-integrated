# v1.8-dev

- 升级抖音下载器 \2\ 依赖为自定义修复版本 (\ccawmiku/f2\)。
- 修复抖音边缘网关新增 \ArgusSecurityPlugin\ 校验导致点赞与收藏列表下载报错 \403 Forbidden\ 的问题（自动截取 \UIFID\ 并注入 \x-tt-argus\ 请求头）。
- 在 Dockerfile 中补充 \git\ 基础组件支持。
