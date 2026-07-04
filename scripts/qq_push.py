#!/usr/bin/env python3
"""qq_push.py — 把日报 HTML 文件通过 QQ Bot API 推送到用户/群

镜像 /opt/wanxia/scripts/push-to-qq.py 的鉴权方式（JSON body 取 token），
增加文件上传（/v2/{type}s/{id}/files，file_type=4）+ msg_type=7 媒体消息发送。
凭证默认从 /opt/wanxia/.env 读（晚霞项目已验证可用的 bot），也可用 env 覆盖。

环境变量（或 --env-file，默认 /opt/wanxia/.env）：
  QQ_APP_ID         — QQ Bot AppID
  QQ_CLIENT_SECRET  — QQ Bot ClientSecret
  QQ_TARGET_TYPE    — group | user（默认 user）
  QQ_TARGET_ID      — 群 openid 或用户 openid

CLI:
  python scripts/qq_push.py <html_path> [--env-file PATH] [--target ID] [--type group|user]

退出码：0 成功；1 未配置；2 发送失败（cron 里 || true 不阻断）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import mimetypes
import os
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_API_BASE = "https://api.sgroup.qq.com"
_DEFAULT_ENV = "/opt/wanxia/.env"

# B 节 audit-log 埋点（audit-2026-07-05-001 WM-QQ-01）：QQ Bot API 为外部 HTTP 出站
# 敏感路径（token 端点 + 上传 + 发消息，凭证 QQ_CLIENT_SECRET 经手）。append-only
# 写 JSONL，对齐 .claude/decisions/audit-log.schema.json。自身异常吞掉——审计日志
# 失败不得影响推送主流程。模式镜像 bocha_search._audit_log。
_AUDIT_DIR = Path(__file__).resolve().parent.parent / ".audit"
_AUDIT_SEQ = 0


def _audit_log(action: str, resource: dict, result: str,
               details: dict | None = None) -> None:
    global _AUDIT_SEQ
    try:
        _AUDIT_SEQ += 1
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        today = now.strftime("%Y-%m-%d")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        seq = f"{os.getpid() % 1000000:06d}{_AUDIT_SEQ:03d}"
        rec = {
            "id": f"audit-{now.strftime('%Y%m%d-%H%M%S')}-{seq}",
            "timestamp": ts,
            "userId": "autonomous-engine",
            "userRole": "engine",
            "action": action,
            "resource": resource,
            "result": result,
            "ip": "local",
            "sensitive": True,
            "sensitiveLevel": "medium",
            "details": details or {},
        }
        path = _AUDIT_DIR / f"audit-{today}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _load_env(path: str | None) -> dict:
    env = dict(os.environ)
    p = Path(path) if path else Path(_DEFAULT_ENV)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.strip()
                # .env 惯例允许 KEY="value" / KEY='value'；strip 仅去空白会保留引号，
                # 致 token/secret 字面含 " 鉴权失败。成对引号才剥，避免误伤值内含引号。
                if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
                    v = v[1:-1]
                env.setdefault(k.strip(), v)
    return env


def _get_token(app_id: str, client_secret: str) -> str:
    """镜像 wanxia：JSON body {appId, clientSecret} POST 取 token。"""
    data = json.dumps({"appId": app_id, "clientSecret": client_secret}).encode("utf-8")
    req = urllib.request.Request(_TOKEN_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 响应体脱敏：QQ Bot token/error body 可能含敏感字段，仅记 status code
        _audit_log("external_call",
                   {"type": "api", "identifier": "qq-bot-token",
                    "baseUrl": _TOKEN_URL},
                   "failure", {"reason": f"HTTP {e.code}"})
        raise RuntimeError(f"取 token HTTP {e.code}") from None
    tok = d.get("access_token")
    if not tok:
        # WM-QQ-01 (audit-2026-07-05-001)：d 是 token 端点的外部响应体（json.loads
        # 而来），非"本地 JSON"——原注释错误。token 端点响应可能含 refresh_token/
        # _scope 等邻近凭证字段，不得整包打到 stderr/cron 日志。只记 key 名。
        _audit_log("external_call",
                   {"type": "api", "identifier": "qq-bot-token",
                    "baseUrl": _TOKEN_URL},
                   "failure",
                   {"reason": "no access_token", "responseKeys": list(d.keys())})
        raise RuntimeError(f"无 access_token (keys={list(d.keys())})") from None
    _audit_log("external_call",
               {"type": "api", "identifier": "qq-bot-token",
                "baseUrl": _TOKEN_URL},
               "success")
    return tok


def _api(url: str, token: str, data: dict | None = None,
         method: str = "POST") -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 响应体脱敏：API error body 可能含用户 openid/token 等敏感字段
        _audit_log("external_call",
                   {"type": "api", "identifier": "qq-bot-api",
                    "baseUrl": url},
                   "failure", {"reason": f"HTTP {e.code}"})
        raise RuntimeError(f"API HTTP {e.code}") from None


def _upload_file(token: str, target_type: str, target_id: str,
                 file_path: Path) -> str:
    """上传文件到 /v2/{type}s/{id}/files，file_type=4=file，返回 file_uuid。"""
    boundary = "----qqpush" + uuid.uuid4().hex
    filename = file_path.name
    mime = mimetypes.guess_type(filename)[0] or "text/html"
    raw = file_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_type"\r\n\r\n4\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="srv_send_msg"\r\n\r\nfalse\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + raw + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"{_API_BASE}/v2/{target_type}s/{urllib.parse.quote(target_id)}/files"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"QQBot {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 响应体脱敏：上传接口错误体可能含文件元数据/用户信息
        _audit_log("external_call",
                   {"type": "api", "identifier": "qq-bot-upload",
                    "baseUrl": url},
                   "failure", {"reason": f"HTTP {e.code}"})
        raise RuntimeError(f"上传 HTTP {e.code}") from None
    fu = (d.get("file_info") or {}).get("file_uuid") or d.get("file_uuid")
    if not fu:
        # WM-QQ-01 (audit-2026-07-05-001)：d 是上传端点的外部响应体，非"本地 JSON"
        # ——原注释错误。只记 key 名，不整包泄露响应体到 stderr/cron 日志。
        _audit_log("external_call",
                   {"type": "api", "identifier": "qq-bot-upload",
                    "baseUrl": url},
                   "failure",
                   {"reason": "no file_uuid", "responseKeys": list(d.keys())})
        raise RuntimeError(f"上传无 file_uuid (keys={list(d.keys())})") from None
    _audit_log("external_call",
               {"type": "api", "identifier": "qq-bot-upload",
                "baseUrl": url},
               "success", {"fileUuid": fu[:10] + "..."})
    return fu


def _send_file_msg(token: str, target_type: str, target_id: str,
                   file_uuid: str, content: str) -> dict:
    url = f"{_API_BASE}/v2/{target_type}s/{urllib.parse.quote(target_id)}/messages"
    return _api(url, token, {
        "msg_type": 7,  # 媒体（文件）
        "media": {"file_info": {"file_uuid": file_uuid}},
        "content": content,
    })


def run(args) -> int:
    env = _load_env(args.env_file)
    app_id = args.app_id or env.get("QQ_APP_ID", "")
    client_secret = args.app_secret or env.get("QQ_CLIENT_SECRET", "")
    target_type = args.type or env.get("QQ_TARGET_TYPE", "user")
    target_id = args.target or env.get("QQ_TARGET_ID", "")

    if not (app_id and client_secret and target_id):
        print("⚠️ QQ_APP_ID/CLIENT_SECRET/TARGET_ID 未配置，跳过", file=sys.stderr)
        return 1
    html_path = Path(args.html_path)
    if not html_path.exists():
        print(f"⚠️ 报告不存在: {html_path}", file=sys.stderr)
        return 1

    try:
        print(f"  [qq] 取 token...", file=sys.stderr)
        token = _get_token(app_id, client_secret)
        print(f"  [qq] 上传 {html_path.name} ({html_path.stat().st_size}B)...", file=sys.stderr)
        fu = _upload_file(token, target_type, target_id, html_path)
        print(f"  [qq] 发送 msg_type=7 → {target_type}...", file=sys.stderr)
        _send_file_msg(token, target_type, target_id, fu,
                       f"热点选题日报 {time.strftime('%Y-%m-%d')}")
        print(f"✅ QQ 推送成功: {target_type} {target_id[:10]}...", file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"❌ QQ 推送失败: {e}", file=sys.stderr)
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description="QQ Bot 推送日报 HTML 文件")
    p.add_argument("html_path")
    p.add_argument("--env-file", default=None, help=f"凭证 .env（默认 {_DEFAULT_ENV}）")
    p.add_argument("--target")
    p.add_argument("--type", choices=["group", "user"], default=None)
    p.add_argument("--app-id")
    p.add_argument("--app-secret")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
