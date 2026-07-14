"""
HealthMonitor - 账号状态与任务健康度监控模块

功能：
1. 实时监控账号池状态（可用、冷却中、已禁用）
2. 追踪各调度任务的执行健康度（是否按频率执行、成功/失败率）
3. 定时输出格式化的健康看板到日志
4. 持久化健康快照到 MongoDB（可选）
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class AccountStatus(str, Enum):
    """账号状态枚举"""
    AVAILABLE = "available"       # 可用
    COOLDOWN = "cooldown"         # 冷却中
    DISABLED = "disabled"         # 已禁用
    UNKNOWN = "unknown"           # 未知（RPC 模式下无法获取账号信息）


class TaskName(str, Enum):
    """任务名称枚举"""
    CRAWL = "crawl"               # 抓取新笔记
    UPDATE_NEW = "update_new"     # 更新 new 源 metrics
    UPDATE_HELPFUL = "update_helpful"  # 更新 helpful 源 metrics


class TaskHealthRecord:
    """单个任务的执行健康记录"""

    def __init__(self, task_name: str, expected_interval_seconds: int):
        self.task_name = task_name
        self.expected_interval_seconds = expected_interval_seconds

        # 执行记录
        self.last_started_at: Optional[datetime] = None
        self.last_succeeded_at: Optional[datetime] = None
        self.last_failed_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_duration_seconds: float = 0.0
        self.last_result: Optional[Dict[str, Any]] = None

        # 累计统计（自启动以来）
        self.total_runs: int = 0
        self.success_runs: int = 0
        self.fail_runs: int = 0
        self.consecutive_failures: int = 0

    def record_start(self):
        """记录任务开始"""
        self.last_started_at = datetime.utcnow()
        self.total_runs += 1

    def record_success(self, result: Optional[Dict[str, Any]] = None, duration: float = 0.0):
        """记录任务成功"""
        self.last_succeeded_at = datetime.utcnow()
        self.last_result = result
        self.last_duration_seconds = duration
        self.success_runs += 1
        self.consecutive_failures = 0

    def record_failure(self, error: str, duration: float = 0.0):
        """记录任务失败"""
        self.last_failed_at = datetime.utcnow()
        self.last_error = error
        self.last_duration_seconds = duration
        self.fail_runs += 1
        self.consecutive_failures += 1

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_runs == 0:
            return 0.0
        return self.success_runs / self.total_runs

    @property
    def is_overdue(self) -> bool:
        """是否超时未执行（距离上次成功超过预期间隔）"""
        if self.last_succeeded_at is None:
            # 从未成功过，检查是否从启动后超时
            if self.last_started_at is None:
                # 从未启动，算超时
                return True
            return False

        now = datetime.utcnow()
        elapsed = (now - self.last_succeeded_at).total_seconds()
        # 允许 20% 的容差
        return elapsed > self.expected_interval_seconds * 1.2

    @property
    def overdue_seconds(self) -> float:
        """超时了多少秒（0 表示未超时）"""
        if not self.is_overdue:
            return 0.0
        if self.last_succeeded_at is None:
            return 0.0
        elapsed = (datetime.utcnow() - self.last_succeeded_at).total_seconds()
        return max(0.0, elapsed - self.expected_interval_seconds)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_name": self.task_name,
            "expected_interval_seconds": self.expected_interval_seconds,
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_succeeded_at": self.last_succeeded_at.isoformat() if self.last_succeeded_at else None,
            "last_failed_at": self.last_failed_at.isoformat() if self.last_failed_at else None,
            "last_error": self.last_error,
            "last_duration_seconds": round(self.last_duration_seconds, 2),
            "total_runs": self.total_runs,
            "success_runs": self.success_runs,
            "fail_runs": self.fail_runs,
            "consecutive_failures": self.consecutive_failures,
            "success_rate": round(self.success_rate, 4),
            "is_overdue": self.is_overdue,
            "overdue_seconds": round(self.overdue_seconds, 1),
        }


class HealthMonitor:
    """
    健康监控器 - 监控账号状态和任务执行健康度

    使用方式：
    1. 在 Monitor 中注册 HealthMonitor
    2. 在各任务执行前后调用 record_task_start / record_task_success / record_task_failure
    3. 定时调用 report() 输出健康看板
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        account_pool=None,
        storage=None,
    ):
        """
        初始化健康监控器

        Args:
            config: 监控配置，包含各任务的预期间隔
            account_pool: AccountPool 实例（直连模式）
            storage: Storage 实例（用于持久化健康快照）
        """
        self.config = config or {}
        self.account_pool = account_pool
        self.storage = storage

        # 是否为 RPC 模式（RPC 模式下无 AccountPool）
        self._rpc_mode = account_pool is None

        # 健康快照持久化开关
        self._persist_snapshots = self.config.get("persist_snapshots", True)

        # 任务健康记录
        self._task_health: Dict[str, TaskHealthRecord] = {}
        self._init_task_health()

        # 监控启动时间
        self._started_at = datetime.utcnow()

        # 上次报告时间
        self._last_report_at: Optional[datetime] = None

        # 账号状态快照（用于趋势检测）
        self._last_account_snapshot: Optional[Dict[str, Any]] = None

    def _init_task_health(self):
        """根据配置初始化各任务的健康记录"""
        monitor_config = self.config.get("monitor", {})

        self._task_health[TaskName.CRAWL] = TaskHealthRecord(
            task_name=TaskName.CRAWL,
            expected_interval_seconds=monitor_config.get("note_crawl", 10),
        )
        self._task_health[TaskName.UPDATE_NEW] = TaskHealthRecord(
            task_name=TaskName.UPDATE_NEW,
            expected_interval_seconds=monitor_config.get("metrics_update", 10),
        )
        self._task_health[TaskName.UPDATE_HELPFUL] = TaskHealthRecord(
            task_name=TaskName.UPDATE_HELPFUL,
            expected_interval_seconds=monitor_config.get("metrics_update", 10),
        )

    # ==================== 任务事件记录 ====================

    def record_task_start(self, task_name: str):
        """记录任务开始执行"""
        if task_name in self._task_health:
            self._task_health[task_name].record_start()

    def record_task_success(
        self,
        task_name: str,
        result: Optional[Dict[str, Any]] = None,
        duration: float = 0.0,
    ):
        """记录任务执行成功"""
        if task_name in self._task_health:
            self._task_health[task_name].record_success(result, duration)

    def record_task_failure(self, task_name: str, error: str, duration: float = 0.0):
        """记录任务执行失败"""
        if task_name in self._task_health:
            self._task_health[task_name].record_failure(error, duration)

    # ==================== 账号状态快照 ====================

    def get_account_snapshot(self) -> Dict[str, Any]:
        """
        获取当前账号池状态快照

        Returns:
            {
                "total": int,
                "available": int,
                "cooldown": int,
                "disabled": int,
                "accounts": [
                    {
                        "username": str,
                        "status": AccountStatus,
                        "success_count": int,
                        "fail_count": int,
                        "consecutive_failures": int,
                        "last_used_at": str,
                        "cooldown_until": str or None,
                        "last_error": str or None,
                    }
                ]
            }
        """
        if self._rpc_mode:
            return {
                "mode": "rpc",
                "total": 0,
                "available": 0,
                "cooldown": 0,
                "disabled": 0,
                "accounts": [],
            }

        accounts = self.account_pool.get_all_accounts()
        now = datetime.utcnow()

        snapshot = {
            "mode": "direct",
            "total": len(accounts),
            "available": 0,
            "cooldown": 0,
            "disabled": 0,
            "accounts": [],
        }

        for acc in accounts:
            if not acc.enabled:
                status = AccountStatus.DISABLED
                snapshot["disabled"] += 1
            elif acc.cooldown_until and now < acc.cooldown_until:
                status = AccountStatus.COOLDOWN
                snapshot["cooldown"] += 1
            else:
                status = AccountStatus.AVAILABLE
                snapshot["available"] += 1

            consecutive_fails = self.account_pool._consecutive_failures.get(acc.username, 0)

            acc_info = {
                "username": acc.username,
                "status": status.value,
                "success_count": acc.success_count,
                "fail_count": acc.fail_count,
                "consecutive_failures": consecutive_fails,
                "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
                "cooldown_until": acc.cooldown_until.isoformat() if acc.cooldown_until else None,
                "last_error": acc.last_error,
            }
            snapshot["accounts"].append(acc_info)

        return snapshot

    # ==================== 健康看板输出 ====================

    def report(self) -> Dict[str, Any]:
        """
        生成并输出健康看板

        Returns:
            完整的健康快照字典
        """
        account_snapshot = self.get_account_snapshot()
        task_health_snapshot = {
            name: record.to_dict()
            for name, record in self._task_health.items()
        }

        uptime = (datetime.utcnow() - self._started_at).total_seconds()

        health_snapshot = {
            "reported_at": datetime.utcnow().isoformat(),
            "uptime_seconds": round(uptime, 0),
            "account_snapshot": account_snapshot,
            "task_health": task_health_snapshot,
        }

        # 输出格式化日志
        self._log_dashboard(account_snapshot, task_health_snapshot, uptime)

        # 持久化到 MongoDB
        if self._persist_snapshots and self.storage:
            self._persist_health_snapshot(health_snapshot)

        self._last_report_at = datetime.utcnow()
        self._last_account_snapshot = account_snapshot

        return health_snapshot

    def _log_dashboard(
        self,
        account_snapshot: Dict[str, Any],
        task_health_snapshot: Dict[str, Any],
        uptime: float,
    ):
        """输出格式化的健康看板到日志"""

        uptime_str = self._format_duration(uptime)

        # ==================== 系统概览 ====================
        logger.info("")
        logger.info("=" * 72)
        logger.info("  HEALTH DASHBOARD")
        logger.info(f"  Uptime: {uptime_str}  |  Mode: {account_snapshot.get('mode', 'unknown')}")
        logger.info("=" * 72)

        # ==================== 账号状态 ====================
        if account_snapshot.get("mode") == "rpc":
            logger.info("  [Accounts] RPC mode - account status not available")
        else:
            total = account_snapshot["total"]
            available = account_snapshot["available"]
            cooldown = account_snapshot["cooldown"]
            disabled = account_snapshot["disabled"]

            # 汇总行
            logger.info(
                f"  [Accounts] Total: {total}  |  "
                f"Available: {available}  |  Cooldown: {cooldown}  |  Disabled: {disabled}"
            )

            # 逐账号详情
            if account_snapshot["accounts"]:
                logger.info("  " + "-" * 68)
                logger.info(
                    f"  {'Username':<16} {'Status':<10} {'Req':>5} {'Ok':>5} "
                    f"{'Fail':>5} {'CF':>3} {'Cooldown Until':<22}"
                )
                logger.info("  " + "-" * 68)
                for acc in account_snapshot["accounts"]:
                    cooldown_str = "--"
                    if acc["cooldown_until"]:
                        try:
                            dt = datetime.fromisoformat(acc["cooldown_until"])
                            remaining = (dt - datetime.utcnow()).total_seconds()
                            if remaining > 0:
                                cooldown_str = self._format_duration(remaining)
                            else:
                                cooldown_str = "expired"
                        except (ValueError, TypeError):
                            cooldown_str = acc["cooldown_until"][:19]

                    status_label = acc["status"].upper()
                    logger.info(
                        f"  {acc['username']:<16} {status_label:<10} "
                        f"{acc['success_count'] + acc['fail_count']:>5} "
                        f"{acc['success_count']:>5} {acc['fail_count']:>5} "
                        f"{acc['consecutive_failures']:>3} {cooldown_str:<22}"
                    )
                logger.info("  " + "-" * 68)

        # ==================== 任务健康度 ====================
        logger.info("")
        logger.info("  [Task Health]")
        logger.info("  " + "-" * 80)
        logger.info(
            f"  {'Task':<18} {'Interval':>10} {'Runs':>5} {'Success':>8} "
            f"{'Errors':>6} {'Overdue':>10}  {'Last Result'}"
        )
        logger.info("  " + "-" * 80)

        for task_name, health in task_health_snapshot.items():
            expected = self._format_duration(health["expected_interval_seconds"])
            overdue_str = "NO"
            if health["is_overdue"]:
                overdue_str = f"+{self._format_duration(health['overdue_seconds'])}"

            # 格式化上次结果
            last_result = health.get("last_result") or {}
            if task_name in ("crawl", "TaskName.CRAWL", TaskName.CRAWL):
                if isinstance(last_result, dict):
                    new_p = last_result.get("new_posts", 0)
                    helpful_p = last_result.get("helpful_posts", 0)
                    if new_p or helpful_p:
                        result_str = f"+{new_p} new +{helpful_p} helpful"
                    else:
                        result_str = "no new posts"
                else:
                    result_str = "--"
            else:
                count = last_result.get("updated_count", 0) if isinstance(last_result, dict) else 0
                if count > 0:
                    result_str = f"{count} posts"
                else:
                    result_str = "no posts"

            logger.info(
                f"  {task_name:<18} {expected:>10} {health['total_runs']:>5} "
                f"{health['success_runs']:>8} {health['fail_runs']:>6} "
                f"{overdue_str:>10}  {result_str:<30}"
            )

            # 显示上次执行时间
            if health.get("last_succeeded_at"):
                last_ok = datetime.fromisoformat(health["last_succeeded_at"])
                ago = (datetime.utcnow() - last_ok).total_seconds()
                logger.info(f"    ↳ Last: {self._format_duration(ago)} ago")

            # 如果有连续失败，输出最后错误
            if health["consecutive_failures"] > 0 and health.get("last_error"):
                logger.info(f"    ↳ Error: {health['last_error'][:80]}")

        logger.info("  " + "-" * 80)
        logger.info("=" * 72)
        logger.info("")

    def _persist_health_snapshot(self, snapshot: Dict[str, Any]):
        """持久化健康快照到 MongoDB"""
        try:
            if hasattr(self.storage, 'save_health_snapshot'):
                self.storage.save_health_snapshot(snapshot)
        except Exception as e:
            logger.debug(f"Failed to persist health snapshot: {e}")

    # ==================== 工具方法 ====================

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 0:
            seconds = 0
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m{secs}s"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h{minutes}m"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d{hours}h"

    def get_summary(self) -> Dict[str, Any]:
        """
        获取简要摘要（供外部调用，如 API 或告警）

        Returns:
            {
                "healthy": bool,      # 整体是否健康
                "accounts": {...},     # 账号快照
                "tasks": {...},        # 任务健康
                "alerts": [...]        # 告警列表
            }
        """
        account_snapshot = self.get_account_snapshot()
        task_health = {
            name: record.to_dict()
            for name, record in self._task_health.items()
        }

        alerts = []

        # 检查账号告警
        if not self._rpc_mode:
            if account_snapshot["available"] == 0 and account_snapshot["total"] > 0:
                alerts.append({
                    "level": "CRITICAL",
                    "type": "account",
                    "message": f"All {account_snapshot['total']} accounts unavailable "
                               f"(cooldown: {account_snapshot['cooldown']}, disabled: {account_snapshot['disabled']})"
                })

            # 检查是否有账号连续失败次数过高
            for acc in account_snapshot.get("accounts", []):
                if acc["consecutive_failures"] >= 5:
                    alerts.append({
                        "level": "WARNING",
                        "type": "account",
                        "message": f"Account '{acc['username']}' has {acc['consecutive_failures']} "
                                   f"consecutive failures (status: {acc['status']})"
                    })

        # 检查任务告警
        for task_name, health in task_health.items():
            if health["is_overdue"]:
                alerts.append({
                    "level": "WARNING",
                    "type": "task",
                    "message": f"Task '{task_name}' is overdue by "
                               f"{self._format_duration(health['overdue_seconds'])} "
                               f"(expected interval: {self._format_duration(health['expected_interval_seconds'])})"
                })

            if health["consecutive_failures"] >= 3:
                alerts.append({
                    "level": "WARNING",
                    "type": "task",
                    "message": f"Task '{task_name}' has {health['consecutive_failures']} "
                               f"consecutive failures"
                })

        # 整体健康判断
        critical_alerts = [a for a in alerts if a["level"] == "CRITICAL"]
        healthy = len(critical_alerts) == 0

        return {
            "healthy": healthy,
            "accounts": account_snapshot,
            "tasks": task_health,
            "alerts": alerts,
        }
