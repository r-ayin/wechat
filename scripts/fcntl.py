# -*- coding: utf-8 -*-
"""fcntl.py — Windows 兼容 shim（Unix fcntl.flock 的 msvcrt 实现）

wechat 管线多个脚本 `import fcntl` 做文件锁；Windows 无此模块。
本 shim 放在 scripts/ 目录下，import 时优先于系统模块被解析到。
锁语义：整文件 1 字节锁（LK_LOCK 带 ~10s 重试），够用且语义接近 flock。
"""
from __future__ import annotations

import msvcrt

LOCK_SH = 1
LOCK_EX = 2
LOCK_UN = 0
LOCK_NB = 4


def flock(fd: int, op: int) -> None:
    if op == LOCK_UN:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    mode = msvcrt.LK_NBLCK if (op & LOCK_NB) else msvcrt.LK_LOCK
    msvcrt.locking(fd, mode, 1)
