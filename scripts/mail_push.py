#!/usr/bin/env python3
"""mail_push.py — 把日报 HTML 文件作为邮件附件发到手机

纯标准库（smtplib + email），零第三方依赖。HTML 作为附件，正文带简短摘要。
端口 465 用 SSL，587/其他用 STARTTLS。

环境变量（从 .wechat-env source，chmod 600 不入库）：
  SMTP_HOST   — SMTP 服务器（如 smtp.qq.com）
  SMTP_PORT   — 端口（465 SSL 默认；587 STARTTLS）
  SMTP_USER   — 发件账号（邮箱地址）
  SMTP_PASS   — 授权码（不是登录密码；QQ/163 邮箱用授权码）
  MAIL_TO     — 收件邮箱
  MAIL_FROM   — 发件人（默认同 SMTP_USER）

CLI:
  python scripts/mail_push.py <html_path> [--to EMAIL] [--subject TEXT]

退出码：0 成功；1 未配置；2 发送失败（cron 里 || true 不阻断）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path

# B 节 audit-log 埋点（audit-2026-07-05-001 WM-MAIL-01）：SMTP 为外部出站敏感路径
# （凭证 SMTP_PASS 经手，登录/发信异常可能含服务器返回的账号提示）。append-only
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


def run(args) -> int:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASS", "")
    to = args.to or os.environ.get("MAIL_TO", "")
    sender = os.environ.get("MAIL_FROM", user)
    subject = args.subject or f"热点选题日报 {time.strftime('%Y-%m-%d')}"

    if not (host and user and pwd and to):
        print("⚠️ SMTP_HOST/USER/PASS/MAIL_TO 未配置，跳过邮件推送", file=sys.stderr)
        return 1
    html_path = Path(args.html_path)
    if not html_path.exists():
        print(f"⚠️ 报告不存在: {html_path}", file=sys.stderr)
        return 1

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(
        f"今日热点选题日报见附件。\n\n报告: {html_path.name} "
        f"({html_path.stat().st_size:,} 字节)\n生成时间: {time.strftime('%Y-%m-%d %H:%M')}\n"
        f"\n(完整报告可本地浏览器打开 HTML 附件查看)")

    # HTML 作为附件（M-001 audit-2026-07-06-022：cap 10MB 防 unbounded read）
    _MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB
    file_size = html_path.stat().st_size
    if file_size > _MAX_ATTACHMENT_BYTES:
        print(
            f"⚠️ HTML 附件过大: {file_size:,} 字节 > {_MAX_ATTACHMENT_BYTES:,} 上限，跳过邮件推送",
            file=sys.stderr,
        )
        _audit_log(
            "external_call",
            {"type": "smtp", "identifier": f"{user}@{host}:{port}", "recipient": to},
            "denied",
            {"reason": f"attachment_too_large size={file_size}"},
        )
        return 1
    msg.add_attachment(
        html_path.read_bytes(),
        maintype="text", subtype="html",
        filename=html_path.name)

    try:
        print(f"  [mail] 连接 {host}:{port}...", file=sys.stderr)
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pwd)
                s.send_message(msg)
        print(f"✅ 邮件已发: {to}", file=sys.stderr)
        _audit_log("external_call",
                   {"type": "smtp", "identifier": f"{user}@{host}:{port}",
                    "recipient": to},
                   "success")
        return 0
    except Exception as e:  # noqa: BLE001
        # WM-MAIL-01 (audit-2026-07-05-001)：SMTP 异常消息（如
        # SMTPAuthenticationError(535, b'...Username and Password not accepted...')）
        # 含服务器返回的账号提示，traceback 更含完整调用栈——原代码两者都打到
        # stderr 进 cron 日志。改为只记异常类型名 + SMTP code（无 PII）。
        code = getattr(e, "smtp_code", None)
        detail = f"smtp_code={code}" if code else "no-smtp-code"
        print(f"❌ 邮件发送失败: {type(e).__name__} ({detail})", file=sys.stderr)
        _audit_log("external_call",
                   {"type": "smtp", "identifier": f"{user}@{host}:{port}",
                    "recipient": to},
                   "failure",
                   {"reason": f"{type(e).__name__} {detail}"})
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description="日报 HTML 邮件附件推送")
    p.add_argument("html_path")
    p.add_argument("--to")
    p.add_argument("--subject")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
