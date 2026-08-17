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


def sum_delta(values):
    """对按时间升序排列的累计计数器求真实增量之和。

    快照里的 total_runs 是进程启动以来的累计值，重启后清零；
    直接求和会被重启/运行时长污染。按相邻差值累加，
    遇到清零（cur < prev）说明进程重启，把当前值作为新起点计入。
    """
    total = 0
    prev = None
    for cur in values:
        if prev is None or cur < prev:
            total += cur
        else:
            total += cur - prev
        prev = cur
    return total


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
            # 累计计数器 → 差值求和，得到当天真实运行/成功/失败次数（重启不污染）
            runs = sum_delta([t.get("total_runs", 0) for t in rec["tasks"][tname]])
            succ = sum_delta([t.get("success_runs", 0) for t in rec["tasks"][tname]])
            fail = sum_delta([t.get("fail_runs", 0) for t in rec["tasks"][tname]])
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

    # ---------- Post 更新次数全景 ----------
    # x_com_post_update_status 每次 post 更新写一条记录，是更新量的完整台账
    update_coll = storage._db["x_com_post_update_status"]
    # MongoDB 存的是 naive UTC datetime，cutoff 需去掉时区信息才能正确比较
    cutoff_dt = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
    pipeline = [
        {"$match": {"captured_at": {"$gte": cutoff_dt}}},
        {"$group": {
            "_id": {
                "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$captured_at"}},
                "source": "$source",
                "status": "$status",
            },
            "count": {"$sum": 1},
        }},
    ]
    per_day_updates = {}
    for r in update_coll.aggregate(pipeline):
        g = r["_id"]
        day = g["day"][5:]  # MM-DD
        per_day_updates.setdefault(day, {}).setdefault(g["source"], {})[g["status"]] = r["count"]

    print(f"\n{'='*100}")
    print("Post 更新次数全景（x_com_post_update_status 逐条更新台账，UTC 日期）")
    print('='*100)
    print(f"{'日期':<12} | {'new 成功':>10} {'new 失败':>8} | "
          f"{'helpful 成功':>12} {'helpful 失败':>10} | {'当日总更新':>10}")
    print('='*100)
    total_updates = 0
    for day in sorted(per_day_updates):
        rec = per_day_updates[day]
        n_ok = rec.get("new", {}).get("success", 0)
        n_fail = sum(v for k, v in rec.get("new", {}).items() if k != "success")
        h_ok = rec.get("helpful", {}).get("success", 0)
        h_fail = sum(v for k, v in rec.get("helpful", {}).items() if k != "success")
        day_total = n_ok + n_fail + h_ok + h_fail
        total_updates += day_total
        print(f"{day:<12} | {n_ok:>10} {n_fail:>8} | {h_ok:>12} {h_fail:>10} | {day_total:>10}")
    print('='*100)
    print(f"查询范围内 post 更新总次数: {total_updates}")

    # ---------- 失败任务的日子 ----------
    print(f"\n{'='*100}")
    print("任务失败日明细（当日失败次数 > 0 的天）:")
    print('='*100)
    fail_days = 0
    for day in sorted(per_day):
        rec = per_day[day]
        row = []
        for tname, label in (("crawl", "crawl"), ("update_new", "update_new"), ("update_helpful", "update_helpful")):
            fail = sum_delta([t.get("fail_runs", 0) for t in rec["tasks"][tname]])
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
