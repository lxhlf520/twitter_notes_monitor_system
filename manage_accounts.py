#!/usr/bin/env python
"""
账号管理脚本 - 用于向账号池添加、查看、管理 Twitter 账号

用法:
    python manage_accounts.py add <username> <cookie>
    python manage_accounts.py list
    python manage_accounts.py disable <username>
    python manage_accounts.py enable <username>
    python manage_accounts.py stats
    python manage_accounts.py import <json_file>
"""
import sys
import logging
from datetime import datetime
from twitter.storage import Storage
from twitter.account_pool import AccountPool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_storage():
    """加载存储连接"""
    import toml
    from pathlib import Path

    config_path = Path(__file__).parent / "config.toml"
    config = toml.load(config_path)

    storage = Storage(
        config["mongodb"]["uri"],
        config["mongodb"]["database"],
        config["mongodb"].get("username"),
        config["mongodb"].get("password")
    )
    storage.connect()
    return storage


def add_account(storage, username: str, cookie: str):
    """添加账号"""
    pool = AccountPool(storage=storage)
    try:
        account = pool.add_account(username, cookie, enabled=True)
        logger.info(f"Account '{username}' added successfully")
    except Exception as e:
        logger.error(f"Failed to add account: {e}")


def list_accounts(storage):
    """列出所有账号"""
    pool = AccountPool(storage=storage)
    accounts = pool.get_all_accounts()

    if not accounts:
        logger.info("No accounts in pool")
        return

    logger.info(f"{'Username':<20} {'Enabled':<10} {'Requests':<10} {'Success':<10} {'Failed':<10} {'Available':<10}")
    logger.info("-" * 80)

    for account in accounts:
        available = "Yes" if account.is_available() else "No"
        logger.info(
            f"{account.username:<20} {str(account.enabled):<10} {account.request_count:<10} "
            f"{account.success_count:<10} {account.fail_count:<10} {available:<10}"
        )


def disable_account(storage, username: str):
    """禁用账号"""
    pool = AccountPool(storage=storage)
    pool.mark_enabled(username, False)
    logger.info(f"Account '{username}' disabled")


def enable_account(storage, username: str):
    """启用账号"""
    pool = AccountPool(storage=storage)
    pool.mark_enabled(username, True)
    logger.info(f"Account '{username}' enabled")


def show_stats(storage):
    """显示统计信息"""
    pool = AccountPool(storage=storage)
    stats = pool.get_account_stats()

    logger.info("Account Pool Statistics")
    logger.info("=" * 40)
    logger.info(f"Total:      {stats['total']}")
    logger.info(f"Enabled:    {stats['enabled']}")
    logger.info(f"Disabled:   {stats['disabled']}")
    logger.info(f"Available:  {stats['available']}")
    logger.info(f"In Cooldown: {stats['in_cooldown']}")


def import_accounts(storage, json_file: str, update_existing: bool = False):
    """从 JSON 文件导入账号

    Args:
        storage: Storage 实例
        json_file: JSON 文件路径
        update_existing: 是否更新已存在的账号（如果 cookie 不同）
    """
    import json
    from pathlib import Path

    pool = AccountPool(storage=storage)

    # 解析文件路径
    file_path = Path(json_file)
    if not file_path.is_absolute():
        file_path = Path(__file__).parent / file_path

    # 加载 JSON 数据
    with open(file_path, 'r', encoding='utf-8') as f:
        accounts_data = json.load(f)

    if not isinstance(accounts_data, list):
        logger.error("JSON file must contain an array of accounts")
        return

    total = len(accounts_data)
    imported = 0
    skipped = 0
    updated = 0
    failed = 0

    logger.info(f"Found {total} accounts in {json_file}")
    logger.info("-" * 60)

    for account_data in accounts_data:
        username = account_data.get("username", "").strip()
        cookie = account_data.get("cookie", "").strip()

        # 跳过空 username 或 cookie
        if not username or not cookie:
            logger.warning(f"Skipping: empty username or cookie")
            skipped += 1
            continue

        # 去重检查：尝试添加账号，如果已存在会抛出异常
        try:
            pool.add_account(username, cookie, enabled=True)
            logger.info(f"Imported: {username}")
            imported += 1
        except Exception as e:
            # 账号已存在
            error_msg = str(e)
            if "duplicate" in error_msg.lower() or "already exists" in error_msg.lower():
                if update_existing:
                    # 更新已存在账号的 cookie
                    try:
                        # 从数据库获取现有账号
                        existing = storage._accounts.find_one({"username": username})
                        if existing and existing.get("cookie") != cookie:
                            # 更新 cookie
                            storage._accounts.update_one(
                                {"username": username},
                                {"$set": {"cookie": cookie, "updated_at": datetime.utcnow()}}
                            )
                            logger.info(f"Updated: {username}")
                            updated += 1
                        else:
                            logger.info(f"Unchanged: {username} (same cookie)")
                            skipped += 1
                    except Exception as update_err:
                        logger.error(f"Failed to update {username}: {update_err}")
                        failed += 1
                else:
                    logger.info(f"Skipped (exists): {username}")
                    skipped += 1
            else:
                logger.error(f"Failed to add {username}: {error_msg}")
                failed += 1

    logger.info("-" * 60)
    result_msg = f"Import completed: {imported} imported"
    if updated > 0:
        result_msg += f", {updated} updated"
    result_msg += f", {skipped} skipped, {failed} failed"
    logger.info(result_msg)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    storage = load_storage()

    try:
        if command == "add":
            if len(sys.argv) < 4:
                logger.error("Usage: python manage_accounts.py add <username> <cookie>")
                sys.exit(1)
            add_account(storage, sys.argv[2], sys.argv[3])

        elif command == "list":
            list_accounts(storage)

        elif command == "disable":
            if len(sys.argv) < 3:
                logger.error("Usage: python manage_accounts.py disable <username>")
                sys.exit(1)
            disable_account(storage, sys.argv[2])

        elif command == "enable":
            if len(sys.argv) < 3:
                logger.error("Usage: python manage_accounts.py enable <username>")
                sys.exit(1)
            enable_account(storage, sys.argv[2])

        elif command == "stats":
            show_stats(storage)

        elif command == "import":
            if len(sys.argv) < 3:
                logger.error("Usage: python manage_accounts.py import <json_file> [--update]")
                sys.exit(1)
            json_file = sys.argv[2]
            update_existing = "--update" in sys.argv
            import_accounts(storage, json_file, update_existing)

        else:
            logger.error(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)

    finally:
        storage.close()


if __name__ == "__main__":
    main()
