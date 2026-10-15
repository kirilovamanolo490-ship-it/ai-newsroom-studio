# 第三方代码、来源与素材

本仓库是 AI 每日观察项目的公开代码与案例快照。自有代码尚未另选开源许可证，未将第三方代码、商标或新闻素材重新许可。

## 代码与运行依赖

| 项目 | 用途 | 收录方式 |
| --- | --- | --- |
| [Remotion](https://github.com/remotion-dev/remotion) | 视频场景、预览、渲染 | `package.json` / lockfile 固定 4.0.534，使用须遵循其适用许可证 |
| [React](https://github.com/facebook/react) | 视频组件 | 包管理依赖 |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | 可选平台上传器 | 固定上游 commit，附本地补丁和 MIT 原许可证，不携带账号资料 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 历史制作中的来源视频获取工具 | 未捆绑源码或可执行文件；需要时独立安装并遵循来源权限 |
| requests / Beautiful Soup / feedparser / python-dateutil | 来源读取与日期解析 | Python 包管理依赖，保留各包自身许可 |
| Playwright | 可选网页交互 QA 与上传器浏览器 | 独立安装，浏览器由其工具管理 |

Seed TTS HTTP 适配器由本项目原先使用的自有工作台代码整理为仓库内模块，只保留实际生产需要的配置、请求和解析逻辑，不包含工作台的凭据或业务数据。

## 新闻来源与原始素材

- 三期案例为项目已有视频、原封面和原字幕；文件哈希与来源入口见 `examples/cases.json`。
- 编辑摘要中的观点、数值与产品状态属于对应期次，不能替代当前官方资料。
- `sources/curated-library.json` 保留来源目录的发现出处，其中部分来源线索来自 [Juya 日报](https://daily.juya.uk)。本仓库不镜像该站文章全文。
- `research/brand-assets/manifest.json` 记录品牌素材的官方来源、文件哈希、尺寸和使用说明。商标和产品图像用于新闻中的对象识别，不表示品牌背书。
- Remotion 案例中的图片、截图和短片段保留原素材信息与报道来源。公开案例不授予第三方素材的额外使用权。

## 本地数据边界

登录会话、API 密钥、个人发布配置、私有回执、浏览器资料和原始抓取缓存不属于公开仓库。复制生产实例时应迁移自己的本地配置，并继续保持这些文件被 Git 忽略。
