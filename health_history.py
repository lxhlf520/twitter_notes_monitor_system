#!/usr/bin/env python
"""
健康快照历史全景分析
读取 MongoDB x_com_health_snapshots 集合，按天聚合任务运行、账号可用性趋势。

用法:
    uv run python health_history.py            # 默认最近 30 天
    uv run python health_history.py 7          # 最近 7 天
    uv run python health_history.py 9999       # 全部历史
"""
import sys
import toml
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import MongoClient
from twitter.storage import Storage


def parse_dt(val):
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    config = toml.load(Path(__file__).parent / "config.toml")
    storage = Storage(
        config["mongodb"]["uri"],
        config["mongodb"]["database"],
        config["mongodb"].get("username"),
        config["mongodb"].get("password"),
    )
    storage.connect()

    coll = storage._db["x_com_health_snapshots"]
    total_docs = coll.count_documents({})

    # 全量拉取（快照 5 分钟一条，30 天约 8640 条，可直接内存处理）
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    docs = list(coll.find({"reported_at": {"$gte": cutoff.isoformat()}}).sort("reported_at", 1))

    if not docs:
        # 兜底：ISO 字符串比较可能因时区后缀失效，直接按字符串排序取最近 N 条
        docs = list(coll.find({}).sort("reported_at", -1).limit(days * 288))
        docs.reverse()

    print(f"\n集合文档总数: {total_docs}")
    print(f"查询范围: 最近 {days} 天，命中 {len(docs)} 条快照")

    if not docs:
        print("无快照数据")
        return

    first = parse_dt(docs[0]["reported_at"])
    last = parse_dt(docs[-1]["reported_at"])
    print(f"时间范围: {first}  ~  {last}")

    # ---------- 任务按天聚合 ----------
    print(f"\n{'='*100}")
    print(f"{'日期':<12} {'重启次数':<8} | {'crawl 运行':>10} {'成功':>7} {'失败':>7} | "
          f"{'update_new 运行':>15} {'成功':>7} {'失败':>7} | {'update_helpful 运行':>18} {'成功':>7} {'失败':>7}")
    print('='*100)

    per_day = {}
    for d in docs:
        dt = parse_dt(d["reported_at"])
        if not dt:
            continue
        day = dt.strftime("%m-%d")
        rec = per_day.setdefault(day, {
            "uptimes": [],
            "tasks": {"crawl": [], "update_new": [], "update_helpful": []},
            "accounts": [],
        })
        rec["uptimes"].append(d.get("uptime_seconds", 0))
        for tname in ("crawl", "update_new", "update_helpful"):
            t = d.get("task_health", {}).get(tname)
            if t:
                rec["tasks"][tname].append(t)
        acc = d.get("account_snapshot", {})
        if acc:
            rec["accounts"].append(acc)

    for day in sorted(per_day):
        rec = per_day[day]
        # 重启检测：uptime 变小说明重启过
        restarts = sum(1 for i in range(1, len(rec["uptimes"])) if rec["uptimes"][i] < rec["uptimes"][i-1])
        parts = [f"{day:<12} {restarts:<8} |"]
        for tname in ("crawl", "update_new", "update_helpful"):
            runs = sum(t.get("total_runs", 0) for t in rec["tasks"][tname])
            succ = sum(t.get("success_runs", 0) for t in rec["tasks"][tname])
            fail = sum(t.get("fail_runs", 0) for t in rec["tasks"][tname])
            parts.append(f" {runs:>10} {succ:>7} {fail:>7} |")
        print("".join(parts))

    # ---------- 账号可用性趋势 ----------
    print(f"\n{'='*100}")
    print(f"{'日期':<12} {'总数':>5} {'可用':>5} {'冷却':>5} {'禁用':>5} | 快照数")
    print('='*100)
    for day in sorted(per_day):
        rec = per_day[day]
        if not rec["accounts"]:
            continue
        last_acc = rec["accounts"][-1]
        print(f"{day:<12} {last_acc.get('total', 0):>5} {last_acc.get('available', 0):>5} "
              f"{last_acc.get('cooldown', 0):>5} {last_acc.get('disabled', 0):>5} | {len(rec['accounts'])}")

    # ---------- 失败任务的日子 ----------
    print(f"\n{'='*100}")
    print("任务失败日明细（当日失败次数 > 0 的天）:")
    print('='*100)
    fail_days = 0
    for day in sorted(per_day):
        rec = per_day[day]
        row = []
        for tname, label in (("crawl", "crawl"), ("update_new", "update_new"), ("update_helpful", "update_helpful")):
            fail = sum(t.get("fail_runs", 0) for t in rec["tasks"][tname])
            if fail > 0:
                row.append(f"{label}={fail}")
        if row:
            fail_days += 1
            print(f"{day}: " + ", ".join(row))
    if fail_days == 0:
        print("（无失败）")

    storage.close()


if __name__ == "__main__":
    main()
