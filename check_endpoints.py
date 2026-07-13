"""检查缓存的端点参数"""
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

client = MongoClient(uri)
db = client[db_name]

# 检查端点参数缓存
doc = db["x_com_signature_cache"].find_one({"_type": "endpoint_params"})
if doc:
    params = doc.get("params", {})
    logger.info(f"端点参数缓存: {len(params)} 个端点")
    for name in sorted(params.keys()):
        ep = params[name]
        logger.info(f"  {name}: {ep.get('endpoint','')[:80]}")
else:
    logger.info("没有端点参数缓存")

client.close()
