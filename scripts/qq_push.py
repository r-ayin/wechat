#!/usr/bin/env python3
"""qq_push.py — 把日报 HTML 文件通过 QQ 官方 Bot OpenAPI 推送到群/私聊

链路：getAppAccessToken → 上传文件拿 file_uuid → 发 msg_type=7 媒体消息。
纯标准库（urllib + multipart），零第三方依赖。

环境变量（从 .wechat-env source，chmod 600 不入库）：
  QQ_APP_ID        — QQ 开放平台 AppID（数字）
  QQ_APP_SECRET    — AppSecret（不是 Token；getAppAccessToken 用它）
  QQ_TARGET        — 目标 group_openid 或 用户 openid
  QQ_TARGET_TYPE   — group | user（默认 group）
  QQ_CONTENT       — 随文件发的文本（默认 "热点选题日报 {date}"）

CLI:
  python scripts/qq_push.py <html_path> [--target ID] [--type group|user]
                                       [--app-id ID] [--app-secret SECRET]

退出码：0 成功；非 0 失败（cron 里 || true 不阻断渲染）。

⚠️ QQ 官方 Bot 主动消息规则：群消息需 bot 已入群；C2C 需用户先私信过 bot
   拿到 openid，且有主动消息配额。凭证需在 qun.qq.com/qqbot 核对。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_API = "https://api.sgroup.qq.com"


def _http(method: str, url: str, *, headers: dict | None = None,
           data: bytes | None = None, timeout: int = 20) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, method=method, data=data,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, dict(e.headers), body


def _get_token(app_id: str, app_secret: str) -> str:
    url = f"{_TOKEN_URL}?appId={urllib.parse.quote(app_id)}&clientSecret={urllib.parse.quote(app_secret)}"
    code, _, body = _http("POST", url)
    if code != 200:
        raise RuntimeError(f"getAppAccessToken HTTP {code}: {body[:300]}")
    d = json.loads(body)
    if "access_token" not in d:
        raise RuntimeError(f"getAppAccessToken 无 token: {body[:300]}")
    return d["access_token"]


def _upload_media(token: str, target: str, target_type: str,
                  file_path: Path) -> str:
    """上传文件拿 file_uuid。file_type=4=file。"""
    # 构建 multipart/form-data
    boundary = "----qqpush" + uuid.uuid4().hex
    filename = file_path.name
    mime = mimetypes.guess_type(filename)[0] or "text/html"
    raw = file_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_type"\r\n\r\n'
        f"4\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="srv_send_msg"\r\n\r\n'
        f"false\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + raw + f"\r\n--{boundary}--\r\n".encode("utf-8")

    base = "groups" if target_type == "group" else "users"
    url = f"{_API}/v2/{base}/{urllib.parse.quote(target)}/media"
    code, _, resp = _http("POST", url, headers={
        "Authorization": f"QQBot {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, data=body)
    if code != 200:
        raise RuntimeError(f"upload media HTTP {code}: {resp[:300]}")
    d = json.loads(resp)
    file_uuid = (d.get("file_info") or {}).get("file_uuid") or d.get("file_uuid")
    if not file_uuid:
        raise RuntimeError(f"upload 无 file_uuid: {resp[:300]}")
    return file_uuid


def _send_msg(token: str, target: str, target_type: str,
              file_uuid: str, content: str) -> str:
    base = "groups" if target_type == "group" else "users"
    url = f"{_API}/v2/{base}/{urllib.parse.quote(target)}/messages"
    payload = {
        "msg_type": 7,  # 媒体（文件）
        "media": {"file_info": {"file_uuid": file_uuid}},
        "content": content,
    }
    code, _, resp = _http("POST", url, headers={
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }, data=json.dumps(payload).encode("utf-8"))
    if code not in (200, 201, 204):
        raise RuntimeError(f"send msg HTTP {code}: {resp[:300]}")
    return resp[:200]


def run(args) -> int:
    app_id = args.app_id or os.environ.get("QQ_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("QQ_APP_SECRET", "")
    target = args.target or os.environ.get("QQ_TARGET", "")
    target_type = args.type or os.environ.get("QQ_TARGET_TYPE", "group")
    content = os.environ.get("QQ_CONTENT") or f"热点选题日报 {time.strftime('%Y-%m-%d')}"

    if not (app_id and app_secret and target):
        print("⚠️ QQ_APP_ID/APP_SECRET/TARGET 未配置，跳过 QQ 推送", file=sys.stderr)
        return 1
    html_path = Path(args.html_path)
    if not html_path.exists():
        print(f"⚠️ 报告不存在: {html_path}", file=sys.stderr)
        return 1

    try:
        print(f"  [qq] 取 token (appId={app_id[:6]}...)", file=sys.stderr)
        token = _get_token(app_id, app_secret)
        print(f"  [qq] 上传文件 {html_path.name} ({html_path.stat().st_size}B)...", file=sys.stderr)
        file_uuid = _upload_media(token, target, target_type, html_path)
        print(f"  [qq] 发送 msg_type=7 → {target_type} {target[:10]}...", file=sys.stderr)
        _send_msg(token, target, target_type, file_uuid, content)
        print(f"✅ QQ 推送成功: {target_type} {target[:10]}...", file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"❌ QQ 推送失败: {e}", file=sys.stderr)
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description="QQ 官方 Bot 推送日报 HTML 文件")
    p.add_argument("html_path")
    p.add_argument("--target")
    p.add_argument("--type", choices=["group", "user"], default=None)
    p.add_argument("--app-id")
    p.add_argument("--app-secret")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
