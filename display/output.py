"""
OutputManager —— 线程安全的终端输出通道

所有并发场景下的 stdout 写入必须通过此模块，
确保 Spinner 渲染线程与 asyncio 主线程不会交错输出导致光标错乱。

非并发场景（welcome 动画、picker 交互）可直接写 stdout。
"""

import sys
import threading

_stdout_lock = threading.RLock()


def write(text):
    """线程安全写入 stdout（不 flush）"""
    with _stdout_lock:
        sys.stdout.write(text)


def write_flush(text):
    """线程安全写入 stdout 并 flush"""
    with _stdout_lock:
        sys.stdout.write(text)
        sys.stdout.flush()


def flush():
    """线程安全 flush stdout"""
    with _stdout_lock:
        sys.stdout.flush()


def acquire():
    """手动获取锁（用于需要多次 write 保持原子性的场景）"""
    _stdout_lock.acquire()


def release():
    """手动释放锁"""
    _stdout_lock.release()
