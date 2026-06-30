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
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path


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

    # HTML 作为附件
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
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"❌ 邮件发送失败: {type(e).__name__}: {e}", file=sys.stderr)
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
