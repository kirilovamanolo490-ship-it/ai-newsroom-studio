# 从来源到一期成片

本项目由脚本与编辑者 / Agent 协作，审核后的编辑数据才进入制作。按 `Asia/Shanghai` 组织期次，来源同时保留原始时区、发布时间、更新时间与发现时间。

## 1. 来源与采集

`sources/official-watchlist.json` 是采集配置，`curated-library.json` 是来源目录。以下命令实际联网并保存本机采集状态：

```sh
python tools/source_watch.py --only openai-news --force
```

不带 `--only` 会检查所有到期且启用的来源。首次读取建立基线，后续区分新条目、内容更新和未标日期的发现。失败或翻页不完整时保留游标，不推进成功水位。编辑前检查 `research/source-watch/latest.json` 的覆盖缺口。

## 2. 规划与审核

```sh
python tools/news_batch.py plan --scheduled-for 2026-10-15T04:00:00+08:00
```

每日 12 个偶数时点：08:00 / 20:00 制作早晚报，其余十个时点制作短版。早报覆盖前日 20:00 至当日 08:00，晚报覆盖 08:00 至 20:00；短版覆盖对应两小时窗口。

复核事实、发布时间和素材后，将审核数据保存为 `research/news-batches/YYYY-MM-DD/HH00/batch.json`。脚本检查事件 ID、内容版本、时间窗口和真实来源运行记录。原始候选不直接标记为 reviewed。

```sh
python tools/news_batch.py bundle --date YYYY-MM-DD --edition morning
python tools/news_batch.py bundle --date YYYY-MM-DD --edition evening
```

汇总保留缺失批次和来源缺口。无有效新闻时可通过 `prepare_status_edition.py` 制作状态期次，它仍要求明确的来源覆盖记录。

## 3. 报告、旁白与素材

输入放入 `research/evidence/YYYY-MM-DD/morning/`、`evening/` 或 `briefing-HH00/`。核心文件为 `report.json` 与 `narration-draft.json`。报告包含窗口、消息、真实来源、图像、品牌和排版信息；旁白的 `scenes` 包含 `id`、标题与原创 `lines`。旁白、导航、封面选择和章节顺序需一致。

公开案例的 `reviewed-data.json` 是阅读摘要，不能重命名成完整生产输入。`src/episodes/generated/` 则保留两期真实可渲染数据及其所需素材，可直接在 Studio 中查看。制作全新一期需要按原规范准备自己的完整输入。

## 4. 制作

配置 TTS、FFmpeg、Node、浏览器及真实素材后，在根目录运行：

```sh
python tools/produce_daily.py --date YYYY-MM-DD --edition morning \
  --narration research/evidence/YYYY-MM-DD/morning/narration-draft.json \
  --render-video --preview-frames
```

短版使用 `--edition briefing --namespace briefing-0400`，旁白路径相应换为 `briefing-0400/`。脚本串联品牌检查、连续配音、字幕、场景准备、TypeScript 检查、渲染与网页。视频通过校验且报告指纹相同时才复用。

## 5. 网页与验收

```sh
python research/report-redesign/build_report.py --input research/evidence/YYYY-MM-DD/morning/report.json
python tools/serve_evidence.py --port 4311
```

打开 `http://127.0.0.1:4311/YYYY-MM-DD/morning/`，检查桌面 / 手机、声音、字幕、章节、原图与来源展开。`--web-only-maintenance` 只维护网页，不将未验收视频记作完成。

新渲染只有 `rendered` 状态。`completion_gate.py` 检查视频、音轨、字幕、章节、报告指纹及验收记录；未完成实际播放验收时返回 incomplete 是预期行为。检查脚本不应伪造验收文件。

## 6. 归档与发布

`python tools/build_newsroom.py` 建立本机 SQLite 索引和阅读页，保留事件、版本、来源与期次关系。平台提交按 [发布接入](publishing.md) 单独执行，不由采集直接触发。定时运行需另外部署，仓库不会安装调度任务。

详细规则见 [早晚报制作规范](../research/report-redesign/早晚报制作规范.md) 与 [完整制作链路](../research/report-redesign/完整制作链路.md)。原文保留迭代背景；公开版路径以本文和 [安装说明](setup.md) 为准。
