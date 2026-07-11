"""初始化 MongoDB 集合和索引"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import toml
import logging
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

config_path = Path(__file__).parent / "config.toml"
config = toml.load(config_path)

uri = config["mongodb"]["uri"]
db_name = config["mongodb"]["database"]
username = config["mongodb"].get("username") or None
password = config["mongodb"].get("password") or None

# 连接 MongoDB
if username and password:
    from urllib.parse import urlparse
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 27017
    auth_uri = f"mongodb://{username}:{password}@{host}:{port}/admin"
    client = MongoClient(auth_uri)
else:
    client = MongoClient(uri)

db = client[db_name]

# 创建所有需要的集合
collections_config = {
    # 主集合
    "twitter_accounts": [
        ("username", ASCENDING, {"unique": True}),
        ("enabled", ASCENDING),
    ],
    "x_com_post_new": [
        ("post_id", ASCENDING, {"unique": True}),
        ("noteId", ASCENDING),
        ("createdAt", DESCENDING),
    ],
    "x_com_post_new_metrics": [
        ("noteId", ASCENDING),
        ("timestamp", DESCENDING),
    ],
    "x_com_post_helpful": [
        ("post_id", ASCENDING, {"unique": True}),
        ("noteId", ASCENDING),
        ("createdAt", DESCENDING),
    ],
    "x_com_post_helpful_metrics": [
        ("noteId", ASCENDING),
        ("timestamp", DESCENDING),
    ],
    "x_com_notes": [
        ("noteId", ASCENDING, {"unique": True}),
        ("createdAt", DESCENDING),
    ],
    "x_com_contributors": [
        ("participantId", ASCENDING, {"unique": True}),
    ],
    "x_com_api_raw": [
        ("timestamp", DESCENDING),
    ],
    "x_com_health_snapshots": [
        ("timestamp", DESCENDING),
    ],
    "x_com_signature_cache": [
        ("endpoint", ASCENDING),
    ],
    "x_com_post_update_status": [
        ("post_id", ASCENDING),
        ("captured_at", DESCENDING),
        ("status", ASCENDING),
    ],
}

# 获取现有集合列表
existing = set(db.list_collection_names())

for coll_name, indexes in collections_config.items():
    if coll_name not in existing:
        db.create_collection(coll_name)
        logger.info(f"✅ 创建集合: {coll_name}")
    else:
        logger.info(f"✓ 集合已存在: {coll_name}")

    # 创建索引
    coll = db[coll_name]
    for idx_config in indexes:
        field, direction = idx_config[0], idx_config[1]
        kwargs = {}
        if len(idx_config) > 2:
            kwargs.update(idx_config[2])
        try:
            # 检查索引是否已存在
            existing_indexes = [idx["name"] for idx in coll.list_indexes()]
            index_name = f"{field}_{direction}"
            if index_name not in existing_indexes:
                coll.create_index([(field, direction)], **kwargs)
                logger.info(f"  ✅ 创建索引: {coll_name}.{index_name}")
            else:
                logger.debug(f"  ✓ 索引已存在: {coll_name}.{index_name}")
        except OperationFailure as e:
            logger.warning(f"  ⚠️  创建索引失败 {coll_name}.{field}: {e}")

logger.info("=" * 50)
logger.info("数据库初始化完成!")
logger.info(f"数据库: {db_name}")
logger.info(f"集合数: {len(list(db.list_collection_names()))}")

# 输出所有集合
for coll in db.list_collection_names():
    count = db[coll].count_documents({})
    logger.info(f"  - {coll}: {count} 条记录")

client.close()
