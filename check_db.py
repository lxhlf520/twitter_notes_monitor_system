"""检查 MongoDB 数据和账号状态"""
import sys
import argparse
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent))
import toml
import logging
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='检查 MongoDB 数据和账号状态')
parser.add_argument('--updates', action='store_true', help='显示 post 更新状态统计')
args = parser.parse_args()

config_path = Path(__file__).parent / "config.toml"
config = toml.load(config_path)
uri = config["mongodb"]["uri"]
db_name = config["mongodb"]["database"]
username = config["mongodb"].get("username") or None
password = config["mongodb"].get("password") or None

if username and password:
    from urllib.parse import urlparse
    parsed = urlparse(uri)
    auth_uri = f"mongodb://{username}:{password}@{parsed.hostname or 'localhost'}:{parsed.port or 27017}/admin"
    client = MongoClient(auth_uri)
else:
    client = MongoClient(uri)

db = client[db_name]

logger.info(f"\n{'='*50}")
logger.info(f"数据库: {db_name}")

for coll_name in sorted(db.list_collection_names()):
    count = db[coll_name].count_documents({})
    logger.info(f"  {coll_name}: {count} 条记录")

# 检查账号状态
accounts = list(db["twitter_accounts"].find())
logger.info(f"\n{'='*50}")
logger.info(f"账号列表 ({len(accounts)}):")
logger.info(f"{'用户名':<25} {'启用':<8} {'请求数':<8} {'成功':<8} {'失败':<8}")
logger.info("-" * 60)
for a in accounts:
    logger.info(f"{a.get('username',''):<25} {str(a.get('enabled','')):<8} {a.get('request_count',0):<8} {a.get('success_count',0):<8} {a.get('fail_count',0):<8}")

# 检查抓取的推文
for coll in ["x_com_post_new", "x_com_post_helpful"]:
    posts = list(db[coll].find().limit(5))
    logger.info(f"\n{'='*50}")
    logger.info(f"{coll} 示例 ({len(posts)}):")
    for p in posts:
        logger.info(f"  post_id={p.get('post_id','N/A')}, author={p.get('author','N/A')}, content={str(p.get('content',''))[:50]}")

if args.updates:
    logger.info(f"\n{'='*50}")
    logger.info("Post 更新状态统计")
    logger.info("-" * 60)

    total_records = db["x_com_post_update_status"].count_documents({})
    success = db["x_com_post_update_status"].count_documents({"status": "success"})
    failed = db["x_com_post_update_status"].count_documents({"status": "failed"})
    deleted = db["x_com_post_update_status"].count_documents({"status": "deleted"})

    logger.info(f"  总更新记录: {total_records}")
    logger.info(f"  成功: {success}  |  失败: {failed}  |  已删除: {deleted}")

    # 各 post 最新状态分组统计
    logger.info(f"\n  各 post 最新更新状态:")
    pipeline = [
        {"$sort": {"captured_at": -1}},
        {"$group": {
            "_id": "$post_id",
            "status": {"$first": "$status"},
            "error": {"$first": "$error"},
            "source": {"$first": "$source"},
            "time": {"$first": "$captured_at"},
            "total_tries": {"$sum": 1},
        }},
        {"$sort": {"time": -1}},
    ]
    latest_statuses = list(db["x_com_post_update_status"].aggregate(pipeline))

    status_count = {"success": 0, "failed": 0, "deleted": 0}
    for s in latest_statuses:
        status_count[s["status"]] = status_count.get(s["status"], 0) + 1

    logger.info(f"    最新状态为 success: {status_count['success']} 条")
    logger.info(f"    最新状态为 failed:  {status_count['failed']} 条")
    logger.info(f"    最新状态为 deleted: {status_count['deleted']} 条")

    # 显示最近的失败记录
    recent_failures = [s for s in latest_statuses if s["status"] == "failed"][:20]
    if recent_failures:
        logger.info(f"\n  最近失败记录 (最新 20 条):")
        logger.info(f"  {'Post ID':>20} {'Source':<8} {'Tries':<6} {'Last Error'}")
        logger.info(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*40}")
        for s in recent_failures:
            err = (s.get("error") or "")[:50]
            t = s.get("time", "")
            if isinstance(t, datetime):
                t = t.strftime("%m-%d %H:%M")
            logger.info(f"  {s['_id']:>20} {s['source']:<8} {s['total_tries']:<6} {err}")

    # 统计更新源分布
    new_count = sum(1 for s in latest_statuses if s["source"] == "new" and s["status"] == "success")
    helpful_count = sum(1 for s in latest_statuses if s["source"] == "helpful" and s["status"] == "success")
    logger.info(f"\n  更新源分布:")
    logger.info(f"    new 最近成功: {new_count}")
    logger.info(f"    helpful 最近成功: {helpful_count}")

client.close()

