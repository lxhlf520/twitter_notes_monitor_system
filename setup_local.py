"""Setup MongoDB user and import accounts"""
import pymongo, sys, csv, logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 1. Create admin user
try:
    c = pymongo.MongoClient('localhost', serverSelectionTimeoutMS=5000)
    c.admin.command('createUser', 'admin', pwd='admin123', roles=['root'])
    logger.info("Admin user created")
except pymongo.errors.OperationFailure as e:
    if 'already exists' in str(e) or 'user already' in str(e).lower():
        logger.info("Admin user already exists")
    else:
        logger.warning(f"Create user failed (may already exist): {e}")

# 2. Now connect with auth
c = pymongo.MongoClient('localhost', username='admin', password='admin123', authSource='admin', serverSelectionTimeoutMS=5000)
db = c['community_notes']
accounts_col = db['twitter_accounts']

# 3. Read CSV and import
path = Path('D:/PycharmProjects/AiSpiderProject/twitter_accounts.csv')
imported = 0
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        username = row.get('username', '').strip()
        cookie = row.get('cookie', '').strip()
        if not username or not cookie:
            continue
        
        doc = {
            "username": username,
            "cookie": cookie,
            "enabled": True,
            "request_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        accounts_col.replace_one({"username": username}, doc, upsert=True)
        logger.info(f"✅ 导入: {username}")
        imported += 1

logger.info(f"完成: 导入 {imported} 个账号")
