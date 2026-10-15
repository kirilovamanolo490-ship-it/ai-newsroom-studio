#!/usr/bin/env python3
"""Interactive account binding. Never uploads content."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from social_publisher import PRIVATE, SAU, SAU_REPO, PLATFORMS, account_check, atomic_json, config, active_bindings


def live_bilibili_categories():
    """Read the logged-in creator's current category tree, without printing credentials."""
    import requests
    c = config()
    path = SAU_REPO / 'cookies' / f"bilibili_{c['platforms']['bilibili']['account']}.json"
    data = json.loads(path.read_text())
    cookie_rows = data.get('cookie_info', {}).get('cookies', data.get('cookies', []))
    cookies = {row['name']: row['value'] for row in cookie_rows if isinstance(row, dict) and 'name' in row and 'value' in row}
    for endpoint in ['https://member.bilibili.com/x/web/archive/pre', 'https://member.bilibili.com/x/vupre/web/archive/types']:
        try:
            response = requests.get(endpoint, cookies=cookies, headers={'Referer':'https://member.bilibili.com/','User-Agent':'Mozilla/5.0'},timeout=20)
            payload = response.json()
            if payload.get('code') != 0:
                continue
            result = []
            def walk(node, parents=''):
                if isinstance(node, list):
                    for item in node: walk(item, parents)
                elif isinstance(node, dict):
                    label = str(node.get('name') or node.get('typename') or '')
                    ident = node.get('id') or node.get('tid')
                    full = f'{parents}/{label}'.strip('/')
                    if ident and label:
                        try: result.append({'id':int(ident), 'name':full})
                        except (ValueError, TypeError): pass
                    for k in ('children','types','type','list','data'):
                        if k in node: walk(node[k], full or parents)
            walk(payload.get('data'))
            if result:
                return list({row['id']:row for row in result}.values())
        except (ValueError, requests.RequestException):
            continue
    return []


def bind(platform):
    c = config()
    account = c['platforms'][platform]['account']
    print(f'\n正在绑定 {platform}。请使用要发布 AI此刻和早晚报的账号登录。', flush=True)
    args = [str(SAU), platform, 'login', '--account', account]
    if platform != 'bilibili': args += ['--headed']
    auth = PRIVATE / 'auth'
    auth.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        result = subprocess.run(args, cwd=auth, env={**os.environ,'TZ':'Asia/Shanghai'}, timeout=900)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        print('登录未完成，可稍后重新运行。', flush=True)
        return False
    valid, why = account_check(platform, account)
    if result.returncode or not valid:
        print(f'{platform}: 登录验证尚未通过 ({why})', flush=True)
        return False
    path = SAU_REPO / 'cookies' / f'{platform}_{account}.json'
    path.chmod(0o600)
    c = config(); c['platforms'][platform]['confirmed'] = True
    atomic_json(PRIVATE/'config.json', c, private=True)
    print(f'{platform}: 登录状态已校验。', flush=True)
    return True


def activate():
    c = config()
    selected = active_bindings(c)
    if not selected:
        print('尚未绑定发布账号，请至少完成一个平台的登录。'); return False
    failures=[]; ready=[]
    for p,b in selected.items():
        if p == 'bilibili' and (not isinstance(b.get('tid'),int) or b['tid']<=0):
            failures.append('bilibili:未选择投稿分区');continue
        ok, reason=account_check(p,b['account'])
        if ok: ready.append(p)
        else: failures.append(p+':'+reason)
    if not ready:
        print('还不能启用发布：'+', '.join(failures));return False
    c['enabled']=True
    atomic_json(PRIVATE/'config.json',c,private=True)
    print('自动发布已开启。每期 AI此刻和早晚报校验完成后同步到已绑定平台：'+', '.join(ready))
    if failures: print('以下已绑定平台需要处理，不影响其他平台：'+', '.join(failures))
    return True


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform',choices=[*PLATFORMS,'all'],default='all')
    parser.add_argument('--activate-only',action='store_true')
    args=parser.parse_args()
    if args.activate_only:return 0 if activate() else 2
    if not sys.stdin.isatty():
        print('请在交互式终端运行账号绑定。');return 2
    selected=PLATFORMS if args.platform=='all' else (args.platform,)
    for p in selected:
        c=config();b=c['platforms'][p]
        if b.get('confirmed') and account_check(p,b['account'])[0]:
            print(f'{p}: 已绑定且有效，跳过。');continue
        if not bind(p):return 2
    c=config()
    if args.platform in ('all', 'bilibili') and c['platforms']['bilibili'].get('confirmed') and not c['platforms']['bilibili'].get('tid'):
        rows=live_bilibili_categories()
        relevant=[r for r in rows if any(word in r['name'] for word in ['科技','人工智能','计算机','资讯','知识'])]
        if not rows:
            print('未能读取 B站当前分区，请让助手读取创作中心后配置分区。');return 2
        for row in relevant or rows: print(f"{row['id']}: {row['name']}")
        raw=input('请输入要使用的 B站分区 ID：').strip()
        found=next((r for r in rows if str(r['id'])==raw),None)
        if not found:print('未选择有效分区，保持发布关闭。');return 2
        c['platforms']['bilibili'].update(tid=found['id'],category_name=found['name'])
        atomic_json(PRIVATE/'config.json',c,private=True)
    if args.platform != 'all':
        # A new bound account joins future episodes when the switch is already on.
        # Logging in alone never changes an explicitly disabled switch.
        return 0
    return 0 if activate() else 2


if __name__=='__main__':raise SystemExit(main())
