"""
独立健康看板 - 从 MongoDB 实时读取健康快照，在独立窗口展示

用法：
    python dashboard.py              # 默认每 5 秒刷新
    python dashboard.py --interval 10   # 每 10 秒刷新一次

特点：
    - 完全独立于主爬虫进程，不影响日志输出
    - 从 MongoDB x_com_health_snapshots 集合读取最新快照
    - 使用 rich 渲染美观的实时表格，Ctrl+C 退出
"""

import argparse
import time
import toml
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from pymongo import MongoClient


def load_config():
    config_path = Path(__file__).parent / "config.toml"
    return toml.load(config_path)


def get_latest_snapshot(collection):
    """从 MongoDB 取最新一条健康快照"""
    doc = collection.find_one(sort=[("reported_at", -1)])
    return doc


def fmt_duration(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "--"
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{int(seconds//60)}m{int(seconds%60)}s"
    elif seconds < 86400:
        return f"{int(seconds//3600)}h{int((seconds%3600)//60)}m"
    else:
        return f"{int(seconds//86400)}d{int((seconds%86400)//3600)}h"


def time_ago(iso_str: str) -> str:
    if not iso_str:
        return "--"
    try:
        dt = datetime.fromisoformat(iso_str)
        secs = (datetime.utcnow() - dt).total_seconds()
        return fmt_duration(secs) + " ago"
    except Exception:
        return "--"


def build_header(snapshot: dict) -> Panel:
    reported = snapshot.get("reported_at", "--")
    uptime = fmt_duration(snapshot.get("uptime_seconds", 0))
    mode = snapshot.get("account_snapshot", {}).get("mode", "unknown")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = Text()
    text.append("  Community Notes Monitor  ", style="bold white on dark_blue")
    text.append(f"   Uptime: {uptime}  |  Mode: {mode}  |  Snapshot: {reported[:19]}  |  Now: {now_str}")
    return Panel(text, box=box.HORIZONTALS, style="dim")


def build_account_table(snapshot: dict) -> Panel:
    acc_snap = snapshot.get("account_snapshot", {})
    mode = acc_snap.get("mode", "unknown")

    if mode == "rpc":
        return Panel(
            Text("  RPC 模式 — 账号状态不可用", style="yellow"),
            title="[bold cyan]Accounts[/bold cyan]",
            box=box.SIMPLE_HEAD,
        )

    total = acc_snap.get("total", 0)
    available = acc_snap.get("available", 0)
    cooldown = acc_snap.get("cooldown", 0)
    disabled = acc_snap.get("disabled", 0)

    table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False)
    table.add_column("Username", style="cyan", min_width=16)
    table.add_column("Status", min_width=10)
    table.add_column("Total", justify="right", min_width=6)
    table.add_column("OK", justify="right", min_width=6)
    table.add_column("Fail", justify="right", min_width=6)
    table.add_column("CF", justify="right", min_width=4)
    table.add_column("Cooldown Remaining", min_width=20)
    table.add_column("Last Used", min_width=12)

    for acc in acc_snap.get("accounts", []):
        status = acc.get("status", "unknown").upper()
        if status == "AVAILABLE":
            status_text = Text(status, style="bold green")
        elif status == "COOLDOWN":
            status_text = Text(status, style="bold yellow")
        else:
            status_text = Text(status, style="bold red")

        cooldown_str = "--"
        if acc.get("cooldown_until"):
            try:
                dt = datetime.fromisoformat(acc["cooldown_until"])
                remaining = (dt - datetime.utcnow()).total_seconds()
                cooldown_str = fmt_duration(remaining) if remaining > 0 else Text("expired", style="dim")
            except Exception:
                cooldown_str = acc["cooldown_until"][:19]

        cf = acc.get("consecutive_failures", 0)
        cf_text = Text(str(cf), style="bold red" if cf >= 3 else "")

        table.add_row(
            acc.get("username", "--"),
            status_text,
            str(acc.get("success_count", 0) + acc.get("fail_count", 0)),
            str(acc.get("success_count", 0)),
            str(acc.get("fail_count", 0)),
            cf_text,
            str(cooldown_str),
            time_ago(acc.get("last_used_at")),
        )

    summary = (
        f"Total: [bold]{total}[/bold]  "
        f"Available: [bold green]{available}[/bold green]  "
        f"Cooldown: [bold yellow]{cooldown}[/bold yellow]  "
        f"Disabled: [bold red]{disabled}[/bold red]"
    )

    return Panel(
        table,
        title=f"[bold cyan]Accounts[/bold cyan]   {summary}",
        box=box.SIMPLE_HEAD,
    )


def build_task_table(snapshot: dict) -> Panel:
    task_health = snapshot.get("task_health", {})

    table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False)
    table.add_column("Task", style="cyan", min_width=18)
    table.add_column("Interval", justify="right", min_width=10)
    table.add_column("Runs", justify="right", min_width=5)
    table.add_column("Success", justify="right", min_width=8)
    table.add_column("Errors", justify="right", min_width=6)
    table.add_column("Overdue", justify="right", min_width=10)
    table.add_column("Last Result", min_width=30)
    table.add_column("Last Run", min_width=14)

    for task_name, h in task_health.items():
        expected = fmt_duration(h.get("expected_interval_seconds", 0))

        is_overdue = h.get("is_overdue", False)
        overdue_secs = h.get("overdue_seconds", 0)
        if is_overdue:
            overdue_text = Text(f"+{fmt_duration(overdue_secs)}", style="bold red")
        else:
            overdue_text = Text("OK", style="bold green")

        # 格式化上次结果
        last_result = h.get("last_result") or {}
        if task_name in ("crawl", "TaskName.CRAWL"):
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

        err_count = h.get("fail_runs", 0)
        fail_style = "bold red" if h.get("consecutive_failures", 0) >= 3 else ""

        table.add_row(
            task_name,
            expected,
            str(h.get("total_runs", 0)),
            str(h.get("success_runs", 0)),
            Text(str(err_count), style=fail_style),
            overdue_text,
            result_str,
            time_ago(h.get("last_succeeded_at")),
        )

    return Panel(
        table,
        title="[bold cyan]Task Health[/bold cyan]",
        box=box.SIMPLE_HEAD,
    )


def build_no_data_panel(reason: str) -> Panel:
    return Panel(
        Text(f"\n  {reason}\n  等待主进程写入第一条健康快照...\n", style="yellow"),
        title="[bold red]No Data[/bold red]",
        box=box.SIMPLE_HEAD,
    )


def build_layout(snapshot: dict | None) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="accounts", ratio=2),
        Layout(name="tasks", ratio=3),
    )

    if not snapshot:
        layout["header"].update(Panel(Text("  Community Notes Monitor — 等待数据...", style="bold yellow"), box=box.HORIZONTALS))
        layout["accounts"].update(build_no_data_panel("MongoDB 中暂无健康快照"))
        layout["tasks"].update(build_no_data_panel("主进程尚未写入健康数据"))
        return layout

    layout["header"].update(build_header(snapshot))
    layout["accounts"].update(build_account_table(snapshot))
    layout["tasks"].update(build_task_table(snapshot))
    return layout


def main():
    parser = argparse.ArgumentParser(description="Community Notes 健康看板")
    parser.add_argument("--interval", type=int, default=5, help="刷新间隔（秒），默认 5")
    args = parser.parse_args()

    config = load_config()
    client = MongoClient(
        config["mongodb"]["uri"],
        username=config["mongodb"].get("username") or None,
        password=config["mongodb"].get("password") or None,
    )
    db = client[config["mongodb"]["database"]]
    collection = db["x_com_health_snapshots"]

    console = Console()
    console.print(f"[bold green]Community Notes 健康看板启动[/bold green]  刷新间隔: {args.interval}s  Ctrl+C 退出")

    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            try:
                snapshot = get_latest_snapshot(collection)
                live.update(build_layout(snapshot))
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                live.update(Panel(Text(f"读取数据失败: {e}", style="bold red"), title="Error"))
                time.sleep(args.interval)

    client.close()
    console.print("[dim]看板已退出[/dim]")


if __name__ == "__main__":
    main()
