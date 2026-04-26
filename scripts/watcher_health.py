#!/usr/bin/env python3
"""
守护进程自愈监控脚本
======================
供 cron 或 systemd 定时调用，检查信号监听守护进程是否存活。
若不存活则自动重启，并通知父代 quant_lead。

用法:
    python scripts/watcher_health.sh              # 检查 + 自动修复
    python scripts/watcher_health.sh --status     # 仅查看
    python scripts/watcher_health.sh --repair     # 强制重启

推荐 crontab 配置（每 5 分钟检查一次）:
    */5 * * * * cd /path/to/project && python3 scripts/watcher_health.sh >> logs/watcher_health.log 2>&1
"""

import os
import sys
import json
import time
import subprocess
import argparse
import smtplib
from pathlib import Path
from datetime import datetime, timezone
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] health: %(message)s",
)
logger = logging.getLogger("watcher_health")

BASE_DIR = Path(__file__).parent.parent
TRADES_DIR = BASE_DIR / "backtests"
PID_FILE = TRADES_DIR / "watcher.pid"
HEARTBEAT_LOG = TRADES_DIR / "watcher_heartbeat.log"
PROCESSED_LOG = TRADES_DIR / "processed_signals.json"
WATCHER_SCRIPT = Path(__file__).parent / "signal_watcher.py"
HEALTH_LOG = TRADES_DIR / "watcher_health.log"
MAX_SILENT_MINUTES = 5  # 心跳静默超过 5 分钟视为失联


def get_health_status() -> dict:
    """获取守护进程综合健康状态"""
    status = {
        "pid": None,
        "alive": False,
        "heartbeat_ok": False,
        "last_heartbeat": None,
        "seconds_since_heartbeat": None,
        "signals_processed": 0,
        "total_executed": 0,
        "missed_heartbeats": 0,
        "needs_repair": False,
    }

    # 检查 PID
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        status["pid"] = pid
        # 检查进程是否存活
        try:
            os.kill(int(pid), 0)
            status["alive"] = True
        except (ProcessLookupError, PermissionError, ValueError):
            status["alive"] = False
    else:
        status["needs_repair"] = True
        status["reason_short"] = "NO_PID_FILE"

    # 检查心跳
    if HEARTBEAT_LOG.exists():
        with open(HEARTBEAT_LOG) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        if lines:
            # 取最后一条心跳
            last_line = lines[-1]
            # 解析时间戳
            try:
                ts_str = last_line.split(" |")[0]
                last_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                elapsed = (now - last_ts).total_seconds()
                status["last_heartbeat"] = ts_str
                status["seconds_since_heartbeat"] = elapsed
                status["heartbeat_ok"] = elapsed < MAX_SILENT_MINUTES * 60
            except (ValueError, IndexError):
                pass

    # 检查处理状态
    if PROCESSED_LOG.exists():
        try:
            with open(PROCESSED_LOG) as f:
                state = json.load(f)
            status["signals_processed"] = len(state.get("processed", []))
            status["total_executed"] = state.get("total_executed", 0)
            status["missed_heartbeats"] = state.get("missed_heartbeats", 0)
        except (json.JSONDecodeError, Exception):
            pass

    # 判断是否需要修复
    if not status["alive"]:
        status["needs_repair"] = True
        status["reason_short"] = "PROCESS_DEAD"
    elif not status["heartbeat_ok"]:
        status["needs_repair"] = True
        status["reason_short"] = f"HEARTBEAT_STALLED ({status.get('seconds_since_heartbeat', '?')}s)"
    elif status.get("missed_heartbeats", 0) >= 3:
        status["needs_repair"] = True
        status["reason_short"] = f"MISSED_HEARTBEATS={status['missed_heartbeats']}"

    return status


def restart_watcher() -> bool:
    """重启守护进程"""
    logger.info("Attempting to restart watcher...")

    # 先杀旧进程
    if PID_FILE.exists():
        old_pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(old_pid), 15)  # SIGTERM
            time.sleep(2)
            logger.info(f"Killed old process PID={old_pid}")
        except (ProcessLookupError, ValueError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 启动新进程
    try:
        log_path = Path(__file__).parent / "watcher_output.log"
        with open(log_path, "a") as log_f:
            proc = subprocess.Popen(
                [sys.executable, str(WATCHER_SCRIPT), "--daemon"],
                stdout=log_f, stderr=log_f,
                cwd=str(BASE_DIR),
                start_new_session=True,
            )
        time.sleep(2)

        # 验证启动
        if PID_FILE.exists():
            new_pid = PID_FILE.read_text().strip()
            logger.info(f"✅ Watcher restarted: PID={new_pid}")
            return True
        else:
            logger.warning("⚠️ Watcher started but no PID file yet")
            return True

    except Exception as e:
        logger.error(f"❌ Failed to restart watcher: {e}")
        return False


def notify_parent(message: str):
    """通知父代 quant_lead（通过写邮件文件）"""
    try:
        from email.message import EmailMessage
        import smtplib
        # 使用 lingtai 内部邮件系统
        msg_path = Path(BASE_DIR) / ".lingtai" / "execution_agent" / "mailbox" / "send"
        msg_path.mkdir(parents=True, exist_ok=True)

        notice = {
            "to": "quant_lead",
            "from": "execution_agent",
            "subject": "【守护进程自愈报告】",
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 直接写入邮件目录 — lingtai 会读取
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        notice_file = msg_path / f"health_notice_{ts}.json"
        with open(notice_file, "w") as f:
            json.dump(notice, f, indent=2)
        logger.info(f"Parent notification written: {notice_file}")

    except Exception as e:
        logger.warning(f"Could not notify parent: {e}")


def health_check(repair: bool = True) -> dict:
    """执行健康检查，必要时自愈"""
    status = get_health_status()

    print("\n" + "=" * 55)
    print("  守护进程健康检查")
    print("=" * 55)
    print(f"  PID:         {status.get('pid', 'N/A')}")
    print(f"  进程存活:    {'✅ ALIVE' if status['alive'] else '❌ DEAD'}")
    print(f"  心跳状态:    {'✅ OK' if status['heartbeat_ok'] else '❌ STALLED'}")
    print(f"  最后心跳:    {status.get('last_heartbeat', 'never')}")
    print(f"  距今:        {status.get('seconds_since_heartbeat', '?')}s")
    print(f"  错失心跳:    {status.get('missed_heartbeats', 0)} 次")
    print(f"  已处理信号:  {status['signals_processed']}")
    print(f"  已执行交易:  {status['total_executed']}")

    if status["needs_repair"]:
        reason = status.get("reason_short", "UNKNOWN")
        print(f"  🚨 需修复:   {reason}")

        if repair:
            print(f"\n  → 正在自动修复...")
            success = restart_watcher()
            if success:
                # 验证修复
                time.sleep(3)
                new_status = get_health_status()
                if new_status["alive"]:
                    print(f"  ✅ 修复成功 (PID={new_status['pid']})")
                    notify_parent(
                        f"守护进程自愈成功\n"
                        f"原因: {reason}\n"
                        f"旧PID: {status.get('pid', '?')} → 新PID: {new_status['pid']}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    print(f"  ❌ 修复失败，进程仍未启动")
                    notify_parent(
                        f"🚨 守护进程修复失败！\n"
                        f"原因: {reason}\n"
                        f"请手动检查: {WATCHER_SCRIPT}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
            else:
                print(f"  ❌ 修复执行失败")
        else:
            print(f"  (--repair 未启用，跳过修复)")
    else:
        print(f"  ✅ 一切正常")

    # 记录健康日志
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    flag = "OK" if not status["needs_repair"] else f"REPAIR_{'OK' if repair and success else 'FAIL'}"
    with open(HEALTH_LOG, "a") as f:
        f.write(f"{ts} | {flag} | PID={status.get('pid','?')} | alive={status['alive']} | heartbeat={status['heartbeat_ok']} | executed={status['total_executed']}\n")

    print("=" * 55)
    return status


def main():
    parser = argparse.ArgumentParser(description="守护进程自愈监控")
    parser.add_argument("--status", action="store_true", help="仅查看健康状态，不修复")
    parser.add_argument("--repair", action="store_true", help="强制重启守护进程")
    parser.add_argument("--check", action="store_true", default=True, help="检查+自愈（默认）")
    args = parser.parse_args()

    if args.status:
        status = get_health_status()
        import json as j
        print(j.dumps(status, indent=2))
        return

    if args.repair:
        success = restart_watcher()
        print(f"Restart: {'✅ SUCCESS' if success else '❌ FAILED'}")
        return

    # 默认：检查 + 自愈
    health_check(repair=True)


if __name__ == "__main__":
    main()
