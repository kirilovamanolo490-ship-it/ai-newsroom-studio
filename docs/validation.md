# 公开版验证记录

检查日期：2026-10-15。对象为独立公开副本，原生产工作区与账号状态未改动。

| 检查 | 结果 |
| --- | --- |
| Python 自动化测试 | 113 项通过，覆盖批次、时间窗口、来源状态、归档、字幕章节、完成条件和平台提交逻辑 |
| npm clean install | `npm ci --no-audit --no-fund` 完成 |
| TypeScript / ESLint | `npm run lint` 通过；公开版修正旧封面组件在提前返回后调用 Hook 的问题 |
| Remotion bundle | `npm run build` 完成 |
| Node 脚本语法 | 渲染入口和网页 QA 入口 `node --check` 通过 |
| 三期案例 SHA-256 | MP4、封面、SRT 与案例清单一致；视频同时匹配原保存的验收记录 |
| 媒体检查 | 三期均为 1920×1080，包含音轨，时长与记录一致 |
| 字幕检查 | 早报 22 条、晚报 31 条、04:00 短版 8 条 |
| 本地展示页 | Chrome 中检查三张原封面、视频控件、字幕入口与来源区；短版可开始播放 |

三期文件时长分别为 216.085、189.739、82.304 秒，视频合计 42,241,030 字节。历史完整播放验收来自原有记录；本次没有对三期再次进行全程听看，也没有重新合成或重新导出成片。

Python 测试中的发布调用使用临时文件与 mock，不上传真实账号。本次没有使用配音额度、改动社交平台绑定或发布新闻。GitHub 仓库发布与视频历史发布状态独立。

公开版还完成了路径与凭据检查，排除 `.secrets`、账号状态、Cookies、原始响应、缓存和依赖目录。原先的私有 TTS 模块整理为本地适配器；媒体工具、浏览器与代理改为可配置。跨平台查找逻辑存在，但完整流程尚未在 Linux / Windows 上实机验收。

复查：

```sh
python -m unittest discover -s tools -p 'test_*.py'
python scripts/verify_examples.py
cd prototypes/daily-brief-video
npm run lint
npm run build
```
