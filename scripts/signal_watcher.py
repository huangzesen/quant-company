#!/usr/bin/env python3
"""
信号监听守护进程 v2
====================
使用 watchdog 文件系统事件监听 signals/ 目录，新文件生成即自动执行。
并含心跳自检，若三息无跳则告警。

运作方式:
1. watchdog 监听 signals/ 目录的 on_created / on_modified 事件
2. 检测到新信号文件 → 自动执行 receive_signal_and_execute.py
3. 已处理信号记录到 backtests/processed_signals.json
4. 每 60 秒记录心跳日志 — 若超过 3 个心跳周期无更新则自警

用法:
    python scripts/signal_watcher.py              # 常驻监听（默认）
    python scripts/signal_watcher.py --daemon     # 常驻监听（显式）
    python scripts/signal_watcher.py --status     # 查看监听状态
    python scripts/signal_watcher.py --kill       # 停止运行中的守护进程
"""

import os
import sys
import json
import time
import signal
import subprocess
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] signal_watcher: %(message)s",
)
logger = logging.getLogger("signal_watcher")

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    logger.warning("watchdog not installed, falling back to polling mode")

BASE_DIR = Path(__file__).parent.parent
SIGNAL_DIR = BASE_DIR / "signals"
TRADES_DIR = BASE_DIR / "backtests"
PROCESSED_LOG = TRADES_DIR / "processed_signals.json"
HEARTBEAT_LOG = TRADES_DIR / "watcher_heartbeat.log"
PID_FILE = TRADES_DIR / "watcher.pid"
EXEC_SCRIPT = Path(__file__).parent / "receive_signal_and_execute.py"

HEARTBEAT_INTERVAL = 60   # 心跳间隔（秒）
MAX_SILENT_HEARTBEATS = 3 # 最多静默次数，超过则自警


def load_state() -> dict:
    """加载已处理信号记录"""
    if PROCESSED_LOG.exists():
        with open(PROCESSED_LOG) as f:
            return json.load(f)
    return {"processed": [], "last_check": None, "total_executed": 0,
            "last_heartbeat": None, "missed_heartbeats": 0}


def save_state(state: dict):
    """保存处理状态"""
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    with open(PROCESSED_LOG, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log_heartbeat(state: dict, msg: str) -> dict:
    """记录心跳"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} | {msg}"
    with open(HEARTBEAT_LOG, "a") as f:
        f.write(entry + "\n")
    logger.info(msg)

    # 更新心跳状态
    state["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    state["missed_heartbeats"] = 0
    save_state(state)
    return state


def check_heartbeat(state: dict):
    """心跳检查线程 — 若超过 MAX_SILENT_HEARTBEATS 次无正常心跳则告警"""
    if state.get("last_heartbeat"):
        last = datetime.fromisoformat(state["last_heartbeat"])
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        if elapsed > HEARTBEAT_INTERVAL * MAX_SILENT_HEARTBEATS:
            missed = state.get("missed_heartbeats", 0) + 1
            state["missed_heartbeats"] = missed
            save_state(state)
            logger.warning(
                f"⚠️ HEARTBEAT MISSED #{missed} — "
                f"last heartbeat {elapsed:.0f}s ago "
                f"(threshold: {HEARTBEAT_INTERVAL * MAX_SILENT_HEARTBEATS}s)"
            )
            if missed >= 3:
                logger.error(
                    f"🚨 CRITICAL: {missed} heartbeats missed! "
                    f"Watcher may be stalled. Check PID {state.get('pid', 'unknown')}"
                )


# ─── 文件系统事件处理器（watchdog 模式） ───────

class SignalFileHandler(FileSystemEventHandler):
    """监听 signals/ 目录的 JSON 信号文件生成事件"""

    def __init__(self):
        self.state = load_state()
        self.processed_ids = set(self.state.get("processed", []))
        self._lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_event(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle_event(event.src_path)

    def on_moved(self, event):
        if event.dest_path and event.dest_path.endswith(".json"):
            self._handle_event(event.dest_path)

    def _handle_event(self, path: str):
        path = Path(path)
        if not path.name.startswith("signal_") or not path.name.endswith(".json"):
            return

        sig_id = path.stem
        with self._lock:
            if sig_id in self.processed_ids:
                return
            self.processed_ids.add(sig_id)

        # 小延迟等文件写完
        time.sleep(1)

        try:
            with open(path) as f:
                data = json.load(f)
            if not data.get("signals"):
                logger.info(f"Skipping {path.name}: no actionable signals")
                self.state["processed"] = list(self.processed_ids)
                save_state(self.state)
                return

            self._execute(path, data)

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Error reading {path.name}: {e}")

    def __init__(self):
        self.state = load_state()
        self.processed_ids = set(self.state.get("processed", []))
        self._lock = threading.Lock()
        self._last_exec_time = {}  # 防风暴：文件级冷却
        self._debounce_seconds = 5  # 同文件 5 秒内不重复执行

    def _execute(self, signal_file: Path, data: dict):
        """执行信号（含防风暴冷却）"""
        sig_id = signal_file.stem

        # 防风暴：同文件冷却
        now = time.time()
        last = self._last_exec_time.get(sig_id, 0)
        if now - last < self._debounce_seconds:
            logger.info(f"Debounced {signal_file.name} ({now-last:.1f}s since last)")
            return

        self._last_exec_time[sig_id] = now
        logger.info(f"🚀 Signal detected: {signal_file.name}")
        n_signals = len(data.get("signals", []))

        try:
            cmd = [
                sys.executable,
                str(EXEC_SCRIPT),
                "--file", str(signal_file),
                "--save-trades",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                  cwd=str(BASE_DIR))

            if proc.returncode == 0:
                logger.info(f"✅ {signal_file.name} executed ({n_signals} signals)")
            else:
                logger.warning(f"⚠️ {signal_file.name} returned code {proc.returncode}")
                if proc.stderr:
                    logger.warning(f"stderr: {proc.stderr[-300:]}")

        except subprocess.TimeoutExpired:
            logger.warning(f"⏰ {signal_file.name} execution timed out (30s)")
        except Exception as e:
            logger.error(f"❌ {signal_file.name} execution failed: {e}")

        # 更新状态
        self.state["processed"] = list(self.processed_ids)
        self.state["total_executed"] = self.state.get("total_executed", 0) + 1
        save_state(self.state)


# ─── 心跳线程 ─────────────────────────────────

class HeartbeatThread(threading.Thread):
    """定期心跳线程"""

    def __init__(self, state_ref: dict, state_lock: threading.Lock, interval: int = 60):
        super().__init__(daemon=True)
        self.state_ref = state_ref
        self.state_lock = state_lock
        self.interval = interval
        self.running = True

    def run(self):
        while self.running:
            time.sleep(self.interval)
            with self.state_lock:
                check_heartbeat(self.state_ref)
                # 记录心跳
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                entry = f"{ts} | ❤️ Heartbeat OK (pid={os.getpid()})"
                with open(HEARTBEAT_LOG, "a") as f:
                    f.write(entry + "\n")
                self.state_ref["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
                save_state(self.state_ref)

    def stop(self):
        self.running = False


# ─── 扫尾扫描（启动时处理积压） ────────────

def scan_existing(state: dict, processed_ids: set) -> set:
    """启动时扫描已有信号文件"""
    signal_files = sorted(SIGNAL_DIR.glob("signal_*.json"))
    for f in signal_files:
        sig_id = f.stem
        if sig_id not in processed_ids:
            try:
                with open(f) as fh:
                    data = json.load(fh)
                if data.get("signals") and len(data["signals"]) > 0:
                    logger.info(f"Found pending signal: {f.name}")
                else:
                    processed_ids.add(sig_id)
            except Exception:
                processed_ids.add(sig_id)

    state["processed"] = list(processed_ids)
    save_state(state)
    return processed_ids


# ─── 状态查询与进程管理 ───────────────────

def show_status():
    """显示监听状态"""
    state = load_state()
    pid = None
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()

    print("\n" + "=" * 55)
    print("  信号监听守护进程 — 状态")
    print("=" * 55)
    print(f"  守护 PID:   {pid or 'not running'}")
    print(f"  已执行:     {state.get('total_executed', 0)} 次")
    print(f"  已处理文件: {len(state.get('processed', []))}")
    print(f"  上次检查:   {state.get('last_check', 'never')}")
    print(f"  上次心跳:   {state.get('last_heartbeat', 'never')}")
    print(f"  错失心跳:   {state.get('missed_heartbeats', 0)} 次")

    if state.get("last_heartbeat"):
        last = datetime.fromisoformat(state["last_heartbeat"])
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        status = "✅ NORMAL" if elapsed < HEARTBEAT_INTERVAL * 2 else "⚠️ WARNING" if elapsed < HEARTBEAT_INTERVAL * MAX_SILENT_HEARTBEATS else "🚨 CRITICAL"
        print(f"  心跳状态:   {status} ({elapsed:.0f}s ago)")

    # 引擎运行进程
    if pid:
        running = os.path.exists(f"/proc/{pid}") if sys.platform != "darwin" else os.path.exists(f"/proc/{pid}") == False
        # macOS 没有 /proc，用 ps
        if sys.platform == "darwin":
            import subprocess
            r = subprocess.run(["ps", "-p", pid, "-o", "pid="], capture_output=True, text=True)
            running = r.returncode == 0
        print(f"  进程存活:   {'✅ ALIVE' if running else '❌ DEAD'}")

    # 待处理信号
    processed_ids = set(state.get("processed", []))
    pending = 0
    for f in sorted(SIGNAL_DIR.glob("signal_*.json")):
        if f.stem not in processed_ids:
            with open(f) as fh:
                data = json.load(fh)
            if data.get("signals") and len(data["signals"]) > 0:
                pending += 1
                print(f"  ⏳ PENDING: {f.name} ({len(data['signals'])} signals)")

    if pending == 0:
        print(f"  待处理:     0 (all caught up)")
    print("=" * 55)


def kill_watcher():
    """停止运行中的守护进程"""
    if not PID_FILE.exists():
        print("No watcher PID file found.")
        return
    pid = PID_FILE.read_text().strip()
    try:
        os.kill(int(pid), signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        print(f"PID {pid} not found (already stopped)")
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        print(f"Error killing PID {pid}: {e}")


# ─── 主入口 ─────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="信号监听守护进程 v2 (watchdog)")
    parser.add_argument("--daemon", action="store_true", help="常驻监听模式（默认）")
    parser.add_argument("--status", action="store_true", help="查看监听状态")
    parser.add_argument("--kill", action="store_true", help="停止运行中的守护进程")
    parser.add_argument("--poll", action="store_true", help="降级为轮询模式（无 watchdog 时自动降级）")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.kill:
        kill_watcher()
        return

    # ── 常驻监听 ──
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    TRADES_DIR.mkdir(parents=True, exist_ok=True)

    # 写 PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # 初始化状态
    state = load_state()
    processed_ids = set(state.get("processed", []))
    processed_ids = scan_existing(state, processed_ids)
    state_lock = threading.Lock()

    log_heartbeat(state, f"🚀 Signal watcher v2 started (pid={os.getpid()}, watchdog={'enabled' if HAS_WATCHDOG else 'fallback-poll'})")
    log_heartbeat(state, f"Watching: {SIGNAL_DIR}")
    log_heartbeat(state, f"Executor: {EXEC_SCRIPT}")

    if HAS_WATCHDOG and not args.poll:
        # ── watchdog 事件驱动模式 ──
        handler = SignalFileHandler()
        observer = Observer()
        observer.schedule(handler, str(SIGNAL_DIR), recursive=False)

        # 心跳线程
        heartbeat = HeartbeatThread(state, state_lock, interval=HEARTBEAT_INTERVAL)
        heartbeat.start()

        try:
            observer.start()
            log_heartbeat(state, "Observer started, waiting for signals...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log_heartbeat(state, "👋 Watcher stopped (SIGINT)")
            observer.stop()
            heartbeat.stop()
        observer.join()
        heartbeat.join()

    else:
        # ── 降级轮询模式 ──
        log_heartbeat(state, "Running in polling mode (interval=60s)")

        def poll_scan():
            nonlocal state, processed_ids
            signal_files = sorted(SIGNAL_DIR.glob("signal_*.json"))
            for f in signal_files:
                sig_id = f.stem
                if sig_id in processed_ids:
                    continue
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    if data.get("signals") and len(data["signals"]) > 0:
                        logger.info(f"🚀 Found signal (poll): {f.name}")
                        cmd = [sys.executable, str(EXEC_SCRIPT), "--file", str(f), "--save-trades"]
                        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(BASE_DIR))
                        state["total_executed"] = state.get("total_executed", 0) + 1
                except Exception as e:
                    logger.warning(f"Poll error: {e}")
                processed_ids.add(sig_id)
                state["processed"] = list(processed_ids)
                save_state(state)

        heartbeat = HeartbeatThread(state, state_lock, interval=HEARTBEAT_INTERVAL)
        heartbeat.start()

        try:
            while True:
                poll_scan()
                check_heartbeat(state)
                time.sleep(60)
        except KeyboardInterrupt:
            log_heartbeat(state, "👋 Watcher stopped (SIGINT)")
            heartbeat.stop()

    log_heartbeat(state, "👋 Watcher exited")
    PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
