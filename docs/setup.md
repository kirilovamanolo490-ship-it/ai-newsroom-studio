# 安装与环境

在仓库根执行命令。推荐 Python 3.12、Node.js 22+。当前验证平台是 macOS Apple Silicon；Linux 需配置自己的 FFmpeg、浏览器和中文字体。采集和发布模块依赖 `fcntl`，完整流程尚不支持 Windows 原生运行。

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd prototypes/daily-brief-video
npm ci
cd ../..
```

`requirements-optional.txt` 仅用于旧 Edge TTS 路径。已有案例使用保存的音频，查看视频和 Studio 预览无需配音凭据。

## 媒体与浏览器

配音处理需要 FFmpeg 和 FFprobe，工具依次查找显式环境变量、系统 PATH、当前平台的 Remotion compositor 包。macOS 自带媒体二进制的库查找目录由公开版调用代码补充。

| 环境变量 | 用途 |
| --- | --- |
| `FFMPEG_PATH` / `FFPROBE_PATH` | 自己安装的可执行文件 |
| `AI_NEWS_PROXY` | 可选代理，默认不强制本地代理 |
| `REMOTION_CHROME_EXECUTABLE` | `render-episode.cjs` 使用的浏览器 |
| `PLAYWRIGHT_EXECUTABLE` | QA 浏览器，也可作为渲染脚本的备用配置 |
| `PLAYWRIGHT_MODULE` | QA 脚本引用的 Playwright 模块路径 |
| `AI_NEWS_ENV_FILE` | TTS 配置文件，默认仓库根 `.env` |
| `AI_NEWS_JUYA_SOURCE_DIR` | 可选来源快照目录，默认寻找最新本地快照 |

Remotion CLI 可使用 `npx remotion browser ensure` 下载浏览器；CLI 自定义浏览器请用 `--browser-executable`。项目按 CSS 字体栈寻找本地中文字体，不再分发系统字体。

## 配音与采集账号

复制 `.env.example` 为 `.env`，填写自己的 `VOLCENGINE_TTS_API_KEY`。新配音调用需要账号拥有指定资源和音色权限，可能计费；默认生产使用 Seed TTS 2.0 Vivi。现有成品与预览不触发新合成。

X 的可选采集接口读取 `.secrets/providers.env` 中的 `TWITTERAPI_IO_KEY`。不接入时关闭 watchlist 中对应条目；RSS 与普通公开网页无需这个密钥。环境变量中的代理与媒体路径需要在 shell 中 `export`，不是所有脚本都会读取 `.env`。

## 可选网页 QA

`verify-edition-qa.cjs` 检查早报和晚报，需要完整生产期次与运行中的本地证据服务器。案例的筛选摘要不能替代完整输入。

```sh
cd prototypes/daily-brief-video
npm install --no-save playwright
npx playwright install chromium
cd ../..
export PLAYWRIGHT_MODULE="$PWD/prototypes/daily-brief-video/node_modules/playwright"
node research/report-redesign/verify-edition-qa.cjs --date YYYY-MM-DD --edition morning
```

自动播放和截图不替代人工完整听看，脚本保留人工审阅标记。

## 本地运行目录

`research/source-watch/` 保存采集状态，`research/news-batches/` 保存审核批次，`research/evidence/` 保存期次输出，`research/publishing/` 保存成片包，`.secrets/` 保存账号与私有回执。可选上传器位于 `GitHub/social-auto-upload/`。这些运行目录均被根 `.gitignore` 排除；真实公开成品固定在 `examples/`，可预览素材固定在视频工程的 `public/episodes/`。
