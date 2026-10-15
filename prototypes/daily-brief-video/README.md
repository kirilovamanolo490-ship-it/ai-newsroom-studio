# AI 每日观察 · Remotion 视频工程

通用 `DailyReport` 使用期次数据生成封面、新闻正文、连续旁白、字幕与章节。默认预览是 2026-10-15 04:00 的真实短版；`Briefing1600` 是 2026-10-13 16:00 的实际制作数据。两期所需素材随 `public/episodes/` 收录。

```sh
npm ci
npm run lint
npm run dev -- --no-open
```

打开 Studio 输出的本地地址。预览现有案例不调用 TTS。重新导出默认案例：

```sh
npx remotion render DailyReport out/demo.mp4
```

`prepare-episode.py` 把完整报告、旁白和素材转换成场景数据；`render-episode.cjs` 处理正式期次的封面、逐场预览与成片。根目录 `tools/produce_daily.py` 串联这些阶段。默认输出 1920×1080、30fps，生成后仍需实际播放验收。

环境变量见 [安装说明](../../docs/setup.md)，新一期制作见 [制作说明](../../docs/production.md)。
