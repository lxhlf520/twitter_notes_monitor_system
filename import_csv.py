"""从 CSV 导入 Twitter 账号到 MongoDB"""
import csv
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from twitter.storage import Storage
from twitter.account_pool import AccountPool

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 加载配置
import toml
config_path = Path(__file__).parent / "config.toml"
config = toml.load(config_path)

storage = Storage(
    config["mongodb"]["uri"],
    config["mongodb"]["database"],
    config["mongodb"].get("username"),
    config["mongodb"].get("password")
)
storage.connect()
logger.info("MongoDB 连接成功")

pool = AccountPool(storage=storage)

csv_path = Path("D:/PycharmProjects/AiSpiderProject/twitter_accounts.csv")
# 也支持从桌面加载
alt_path = Path("C:/Users/13662/Desktop/twitter_accounts.csv")

path = csv_path if csv_path.exists() else alt_path
logger.info(f"读取文件: {path}")

imported = 0
skipped = 0
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        username = row.get('username', '').strip()
        cookie = row.get('cookie', '').strip()
        if not username or not cookie:
            logger.warning(f"跳过空行: username={username}")
            continue
        
        # 处理 CSV 中内嵌的双引号转义
        # CSV 中 "" → ", 但 Python csv 模块已处理
        try:
            pool.add_account(username, cookie, enabled=True)
            logger.info(f"✅ 导入: {username}")
            imported += 1
        except Exception as e:
            logger.error(f"❌ 导入失败 {username}: {e}")
            skipped += 1

logger.info(f"完成: 导入 {imported}, 跳过 {skipped}")
