# 可选平台发布

支持 B站、抖音、小红书、YouTube。先按 [固定版本安装说明](../third_party/social-auto-upload/README.md) 准备上传器，再配置自己的账号。统一入口 `tools/social_publisher.py` 会检查同一期报告、成片、封面和验收记录。

## 配置与登录

```sh
mkdir -p .secrets/social-publisher
chmod 700 .secrets .secrets/social-publisher
cp config/social-publisher.example.json .secrets/social-publisher/config.json
chmod 600 .secrets/social-publisher/config.json
```

为目标平台填写自己的账号别名，把平台的 `enabled` 设为 `true`。`confirmed` 由登录验证写入；B站还需选择有效分区 `tid`。模板总开关为 `false`，按自己的安排明确开启；`not_before` 可设为带时区的起始时间，排除旧期次。

```sh
python tools/social_login.py --platform douyin
python tools/social_publisher.py doctor --check-accounts
```

登录可能打开浏览器或显示二维码，由账号持有人完成。单平台绑定不会开启关闭的总开关；`--platform all` 会在绑定结束后尝试启用总开关，请按自己的接入范围选择。

## 准备与实际提交

文案取封面重点，保留栏目、日期与短版时点。长标题需要编辑，不机械截断。需要完整生产目录及验收记录；`examples/` 中的摘要不能直接作为发布包。

```sh
# 仅准备本机成片包
python tools/social_publisher.py prepare --date YYYY-MM-DD --edition morning
# 实际上传已绑定、已启用且预检通过的平台
python tools/social_publisher.py dispatch --date YYYY-MM-DD --edition morning
# 短版拥有独立命名空间
python tools/social_publisher.py dispatch --date YYYY-MM-DD --edition briefing --namespace briefing-0400
# 查询本机保存的状态
python tools/social_publisher.py status --date YYYY-MM-DD --edition morning
```

## 状态与恢复

| 状态 | 含义 |
| --- | --- |
| `skipped_unbound` | 未绑定或未启用 |
| `prepared` | 本机成片包已准备 |
| `submitted_unverified` + 退出码 0 | 已返回提交成功，未独立确认公开 |
| `processing` | 平台处理 |
| `public` | 回执记录公开结果 |
| `rejected` / `ambiguous` | 明确失败或结果不确定，需要处理 |

代码将明确提交成功、processing 和 public 视为该平台提交流程完成，保留原始状态；成功回执后不例行重新登录或重传。另有平台观察证据时可以 `reconcile` 更新。单平台失败不导致其他平台重发，结果含糊时先查明。账号、会话与回执保留在本机 `.secrets/` 和被 Git 忽略的上传器目录。
