"""检查 MongoDB 数据和账号状态"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import toml
import logging
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

client.close()
