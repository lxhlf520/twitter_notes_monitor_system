import argparse
import logging
import logging.handlers
import os
import toml
from pathlib import Path

from twitter.client import Client
from twitter.storage import Storage
from twitter.monitor import Monitor, TaskMode
from twitter.account_pool import AccountPool
from twitter.health_monitor import HealthMonitor


def setup_logging():
    """配置日志：控制台 + 滚动文件（app.log 全量，error.log 只写 ERROR+）"""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler（INFO+）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    # app.log：按天滚动，保留 7 天（INFO+，全量）
    app_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(fmt)

    # error.log：按天滚动，保留 30 天（ERROR+ 专用）
    error_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "error.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 避免重复添加（uv run 热重载场景）
    if not root.handlers:
        root.addHandler(console_handler)
        root.addHandler(app_handler)
        root.addHandler(error_handler)
    else:
        root.handlers.clear()
        root.addHandler(console_handler)
        root.addHandler(app_handler)
        root.addHandler(error_handler)


setup_logging()
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Twitter Community Notes 监控器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式示例:
  python main.py --task crawl      # 只运行 note_crawl 任务
  python main.py --task update     # 只运行 metrics_update 任务
  python main.py --task all        # 同时运行两个任务（默认）
        """,
    )
    parser.add_argument(
        "--task",
        type=str,
        choices=["crawl", "update", "all"],
        default="all",
        help="选择运行的任务: crawl=抓取笔记, update=更新指标, all=全部运行 (默认: all)",
    )
    return parser.parse_args()


def get_config():
    """
    加载配置，支持环境变量覆盖

    优先级：环境变量 > config.toml
    """
    config_path = Path(__file__).parent / "config.toml"
    config = toml.load(config_path)

    # 从环境变量读取 Twitter Cookie（优先级更高）
    twitter_cookie = os.environ.get("TWITTER_COOKIE")
    if twitter_cookie:
        config["twitter"]["cookie"] = twitter_cookie

    # 从环境变量读取 MongoDB 配置
    mongodb_uri = os.environ.get("MONGODB_URI")
    if mongodb_uri:
        config["mongodb"]["uri"] = mongodb_uri

    return config


def main():
    args = parse_args()
    config = get_config()

    # # 解析任务模式
    task_mode_map = {
        "crawl": TaskMode.CRAWL,
        "update": TaskMode.UPDATE,
        "all": TaskMode.ALL,
    }
    task_mode = task_mode_map[args.task]
    # task_mode = TaskMode.UPDATE
    # 初始化组件
    proxy_url = config["proxy"].get("url") or None
    rpc_url = config["rpc"].get("base_url") or None
    rpc_timeout = config["rpc"].get("timeout") or None
    rpc_mode = config["mode"].get("is_rpc") or False
    save_raw_response = config.get("storage", {}).get("save_raw_response", False)
    storage = Storage(
        config["mongodb"]["uri"],
        config["mongodb"]["database"],
        config["mongodb"].get("username"),
        config["mongodb"].get("password")
    )
    storage.connect()

    # 仅在开启原始响应落库时把 storage 注入 Client；关闭时 Client 走 no-op
    client_storage = storage if save_raw_response else None
    logger.info(f"Raw API response persistence: {'enabled' if save_raw_response else 'disabled'}")

    
    # 如果没有账号，使用 fallback cookie（如果有配置）
    # accounts = account_pool.get_all_accounts()
    # if not accounts:
    #     fallback_cookie = config["twitter"].get("cookie")
    #     if fallback_cookie:
    #         logger.info("No accounts in pool, using fallback cookie from config")
    #         account_pool.add_account("fallback", fallback_cookie, enabled=True)

    # 初始化 Client，传入账号池
    client: Client = None
    account_pool = None
    if not rpc_mode:
        # 读取速率限制配置
        per_account_min_interval = config.get("account", {}).get("per_account_min_interval", 0)
        max_workers = config.get("monitor", {}).get("max_workers", 100)

        # 初始化账号池
        account_pool = AccountPool(
            storage=storage,
            proxy=proxy_url,
            cooldown_after_3_fails=config.get("account", {}).get("cooldown_after_3_fails", 1800),
            cooldown_after_5_fails=config.get("account", {}).get("cooldown_after_5_fails", 7200),
            cooldown_after_10_fails=config.get("account", {}).get("cooldown_after_10_fails", 86400),
            min_interval=per_account_min_interval,
        )
        account_pool.load_accounts_from_db()
        client = Client(proxy=proxy_url, account_pool=account_pool, storage=client_storage)
        client.init_client()
        # 输出账号池统计
        pool_stats = account_pool.get_account_stats()
        logger.info(f"账号池: {pool_stats['total']} total, {pool_stats['available']} available, "
                   f"min_interval={per_account_min_interval}s, max_workers={max_workers}")

        # Cookie 有效性校验：自动禁用无效账号
        if pool_stats['total'] > 0:
            verify_result = account_pool.verify_all_accounts(max_workers=20)
            if verify_result['invalid'] > 0:
                logger.warning(
                    f"已自动禁用 {verify_result['invalid']} 个 cookie 无效的账号，"
                    f"请使用 manage_accounts.py 更新其 cookie 后重新启用"
                )
            pool_stats = account_pool.get_account_stats()
            logger.info(f"校验后账号池: {pool_stats['available']} available, "
                       f"{pool_stats['disabled']} disabled, {pool_stats['in_cooldown']} cooldown")
    else:
        client = Client(rpc_model=rpc_mode, rpc_url=rpc_url, rpc_timeout=rpc_timeout, storage=client_storage)
        
        
        
    # 初始化健康监控器
    health_config = config.get("health", {})
    health_enabled = health_config.get("enabled", True)
    health_monitor = None

    if health_enabled:
        health_monitor = HealthMonitor(
            config={
                "monitor": config["monitor"],
                "persist_snapshots": health_config.get("persist_snapshots", True),
                "health_report_interval": health_config.get("report_interval", 300),
            },
            account_pool=account_pool if not rpc_mode else None,
            storage=storage,
        )
        logger.info("Health monitor enabled")
    else:
        logger.info("Health monitor disabled")

    monitor = Monitor(client, storage, config["monitor"], task_mode=task_mode, health_monitor=health_monitor, account_pool=account_pool)
    logger.info(f"Task mode: {task_mode.value}")
    logger.info("Starting Community Notes Monitor...")
    logger.info(f"Crawl interval: {config['monitor']['note_crawl']}s, Update interval: {config['monitor']['metrics_update']}s")
    logger.info(
        "Update strategy: "
        f"new={config['monitor']['new_min_seconds']}s-{config['monitor']['new_max_seconds']}s/{config['monitor']['new_max_days']}d, "
        f"new_to_helpful={config['monitor']['new_to_helpful_min_seconds']}s-{config['monitor']['new_to_helpful_max_seconds']}s/{config['monitor']['new_to_helpful_max_days']}d, "
        f"helpful={config['monitor']['helpful_min_seconds']}s-{config['monitor']['helpful_max_seconds']}s/{config['monitor']['helpful_max_days']}d"
    )

    try:
        monitor.start()
    except KeyboardInterrupt:
        logger.info("Stopping monitor...")
    finally:
        # 服务停止时批量更新账号统计信息到数据库
        if not rpc_mode and account_pool:
            account_pool.shutdown()
        storage.close()


if __name__ == "__main__":
    main()
