from __future__ import annotations
import json
import logging
import time
import signal
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from .client import Client
from .storage import Storage
from .tweet import Tweet
from .health_monitor import HealthMonitor, TaskName

try:
    import schedule
except ImportError:
    schedule = None

logger = logging.getLogger(__name__)


class TaskMode(Enum):
    """任务运行模式"""
    CRAWL = "crawl"          # 只运行 note_crawl 任务
    UPDATE = "update"        # 只运行 metrics_update 任务
    ALL = "all"              # 同时运行两个任务


class Monitor:
    """
    Community Notes 监控器 - 支持双源追踪和独立更新策略

    数据源：
    - new: 最新的 Community Notes 推文
    - helpful: 已标记为有帮助的推文

    更新策略：
    - new note: 每 new_interval_seconds 秒更新，最多追踪 new_max_days 天
    - new note 变成 helpful: 每 new_to_helpful_interval_seconds 秒更新，最多追踪 new_to_helpful_max_days 天
    - helpful note: 每 helpful_interval_seconds 秒更新，最多追踪 helpful_max_days 天
    """

    def __init__(
        self,
        client: Client,
        storage: Storage,
        config: Optional[Dict[str, Any]] = None,
        task_mode: TaskMode = TaskMode.ALL,
        health_monitor: Optional[HealthMonitor] = None,
    ):
        """
        初始化监控器

        Args:
            client: Twitter API 客户端
            storage: 存储器
            config: 更新频率配置，默认为 None 时使用默认值
            task_mode: 任务运行模式，默认为 ALL（同时运行两个任务）
            health_monitor: 健康监控器实例，如果为 None 则不进行健康监控
        """
        self.client = client
        self.storage = storage
        self.task_mode = task_mode
        self.health_monitor = health_monitor

        # 默认配置 - 双源独立策略
        default_config = {
            'crawl': 60,
            'update': 300,
            # new note 策略
            'new_interval_seconds': 14400,           # 4小时
            'new_max_days': 6,                       # 未变helpful最多追踪6天
            'new_to_helpful_interval_seconds': 7200, # 变helpful后间隔2小时
            'new_to_helpful_max_days': 14,           # 变helpful后追踪14天
            # helpful note 策略
            'helpful_interval_seconds': 7200,        # 2小时
            'helpful_max_days': 14,                  # 最多追踪14天
            # 多线程配置
            'max_workers': 20,
            'fetch_parallel': True,
        }

        if config:
            default_config.update(config)

        self.config = default_config

        # 线程池（类属性，生命周期与 Monitor 实例相同）
        max_workers = self.config.get('max_workers', 10)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def run_cycle(self) -> Dict[str, Any]:
        """
        执行一次完整的抓取周期

        Returns:
            包含统计信息的字典
        """
        result = {
            'new_posts': 0,
            'helpful_posts': 0,
            'new_metrics': 0,
            'helpful_metrics': 0,
            'errors': []
        }

        try:
            logger.info("Fetching new posts from 'new' source...")
            save_posts = self.fetch_posts()
            result['new_posts'] = save_posts['new_posts']
            result['helpful_posts'] = save_posts['helpful_posts']
            result['errors'].extend(save_posts['errors'])

            # 2. 根据分级策略更新 metrics
            logger.info("Updating metrics for 'new' source...")
            result['new_metrics'] = self.update_metrics_by_source('new')

            logger.info("Updating metrics for 'helpful' source...")
            result['helpful_metrics'] = self.update_metrics_by_source('helpful')

        except Exception as e:
            error_msg = f"Error in cycle: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        logger.info(f"Cycle completed: new={result['new_posts']}, "
                   f"helpful={result['helpful_posts']}, "
                   f"new_metrics={result['new_metrics']}, "
                   f"helpful_metrics={result['helpful_metrics']}")

        return result

    def fetch_posts(self) -> int:
        """
        抓取并保存新推文


        Returns:
            新抓取的推文数量
        """
        start_time = time.time()
        if self.health_monitor:
            self.health_monitor.record_task_start(TaskName.CRAWL)

        new_count = 0
        helpful_count = 0
        def save_post(tweet: Tweet, source: str):
            nonlocal new_count, helpful_count
            if source == "helpful" and not self.storage.helpful_post_exists(tweet.id):
                # 保存 Post 静态信息
                post_data = self._tweet_to_post_data(tweet, 'helpful')
                self.storage.save_helpful_post(post_data)
                # 保存初始 Metrics
                self.storage.save_helpful_metrics(self._extract_metrics(tweet, 'helpful'))
                self._save_note_and_contributors(tweet.id)
                new_count += 1
                logger.info(f"[HELPFUL] Captured tweet: {tweet.id}")
            elif source == "new" and not self.storage.new_post_exists(tweet.id):
                # self.storage.save_new_post(self._tweet_to_dict(tweet, source))
                post_data = self._tweet_to_post_data(tweet, 'new')
                self.storage.save_new_post(post_data)
                # 保存初始 Metrics
                self.storage.save_new_metrics(self._extract_metrics(tweet, 'new'))
                # 获取并保存 Note/Contributor 信息
                self._save_note_and_contributors(tweet.id)
                helpful_count += 1
                logger.info(f"[NEW] Captured tweet: {tweet.id}")
    
        try:
            # communitynotes_rated_helpful 返回包含两个源的字典
            result = self.client.communitynotes_rated_helpful()

            helpful: List[Tweet] = result.get('rated_helpful', []) or []
            new: List[Tweet] = result.get('new', []) or []

            futures = {
                self._executor.submit(save_post, tweet, 'helpful'): 'helpful'
                for tweet in helpful
            } | {
                self._executor.submit(save_post, tweet, 'new'): 'new'
                for tweet in new
            }
            for future in as_completed(futures):
                if future.exception():
                    logger.error(
                        f"Error processing tweet: {future.exception()}",
                        exc_info=future.exception(),
                    )
        except Exception as e:
            error_msg = f"Error fetching posts: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            if self.health_monitor:
                self.health_monitor.record_task_failure(TaskName.CRAWL, error_msg, time.time() - start_time)
        else:
            if self.health_monitor:
                self.health_monitor.record_task_success(
                    TaskName.CRAWL,
                    {"new_posts": new_count, "helpful_posts": helpful_count},
                    time.time() - start_time
                )
        return { "new_posts": new_count, "helpful_posts": helpful_count, "errors": []}
    
    

    def _save_note_and_contributors(self, tweet_id: str) -> None:
        """
        获取并保存特定推文的 Note 和 Contributor 信息

        Args:
            tweet_id: 推文 ID
        """
        try:
            note_data = self.client.communitynotes_detail(tweet_id)
            if note_data:
                # 保存 Notes
                self.storage.save_notes(note_data['notes'])
                # 保存 Contributors
                self.storage.save_contributors(note_data['contributors'])
                logger.info(f"Saved {len(note_data['notes'])} notes for tweet {tweet_id}")
        except Exception as e:
            logger.debug(f"Failed to fetch notes for tweet {tweet_id}: {e}")

    def update_metrics_by_source(self, source: str) -> int:
        """
        根据分级策略更新指定源的 metrics（多线程并发更新）

        Args:
            source: 数据源，'new' 或 'helpful'

        Returns:
            更新的推文数量
        """
        task_name = TaskName.UPDATE_NEW if source == 'new' else TaskName.UPDATE_HELPFUL
        start_time = time.time()
        if self.health_monitor:
            self.health_monitor.record_task_start(task_name)

        updated_count = 0
        errors = []

        try:
            # 获取需要更新的推文列表
            posts_to_update = self.storage.get_posts_needing_update(source, self.config)

            logger.info(f"Found {len(posts_to_update)} posts needing update for {source}")

            if not posts_to_update:
                return 0


            def update_single_post(post: dict) -> bool:
                """更新单个推文的 metrics（无 RPC 并发限制，直接 HTTP 请求）"""
                try:
                    post_id = post.get('post_id') or post.get('tweet_id')
                    if not post_id:
                        return False

                    tweet = self.client.get_tweet_by_id(post_id)

                    if tweet:
                        metrics = self._extract_metrics(tweet, source)
                        # 使用 post_id 作为关联键
                        metrics['post_id'] = post_id
                        if source == 'new':
                            self.storage.save_new_metrics(metrics)
                        else:
                            self.storage.save_helpful_metrics(metrics)

                        return True

                except Exception as e:
                    pid = post.get('post_id') or post.get('tweet_id', 'unknown')
                    logger.error(
                        f"Failed to update {pid}: {type(e).__name__}: {e}",
                        exc_info=True,
                    )
                    errors.append(f"Failed to update {pid}: {type(e).__name__}: {e}")
                    return False

            # 使用类属性线程池并发更新
            future_to_post = {
                self._executor.submit(update_single_post, post): post
                for post in posts_to_update
            }

            # 收集结果
            for future in as_completed(future_to_post):
                try:
                    if future.result():
                        updated_count += 1
                except Exception as e:
                    post = future_to_post[future]
                    logger.error(
                        f"Unexpected error updating {post.get('tweet_id', 'unknown')}: {type(e).__name__}: {e}",
                        exc_info=True,
                    )
                    errors.append(f"Unexpected error: {type(e).__name__}: {e}")

        except Exception as e:
            logger.error(f"Error updating metrics for {source}: {type(e).__name__}: {e}", exc_info=True)
            errors.append(f"Error updating metrics for {source}: {type(e).__name__}: {e}")
            if self.health_monitor:
                self.health_monitor.record_task_failure(task_name, str(e), time.time() - start_time)
        else:
            if self.health_monitor:
                self.health_monitor.record_task_success(
                    task_name,
                    {"source": source, "updated_count": updated_count},
                    time.time() - start_time
                )

        return updated_count

    def _tweet_to_post_data(self, tweet: Tweet, source: str) -> dict:
        """
        将 Tweet 对象转换为 Post 静态信息字典

        Args:
            tweet: Tweet 对象
            source: 数据源

        Returns:
            Post 字典（符合 REQUIREMENTS.md 3.1 格式）
        """
        return {
            "author": tweet.user.screen_name or "",
            "user_id": tweet.user.id,
            "pub_time": tweet.created_at,
            "post_id": tweet.id,
            "comment_count": tweet.reply_count or 0,
            "repost_count": tweet.retweet_count or 0,
            "like_count": tweet.favorite_count or 0,
            "view_count": tweet.view_count or 0,
            "captured_at": int(datetime.utcnow().timestamp() * 1000),
            "content": tweet.full_text,
            "url": tweet.url,
            "source_data": json.dumps(tweet._data, ensure_ascii=False),
        }

    def _post_to_metrics(self, post: dict, source: str) -> dict:
        """
        将 Post 字典转换为 metrics 数据

        Args:
            post: Post 字典（来自 parse_note_data）
            source: 数据源

        Returns:
            metrics 字典
        """
        return {
            "post_id": post["post_id"],
            "source": source,
            "repost_count": post.get("repost_count", 0),
            "like_count": post.get("like_count", 0),
            "view_count": post.get("view_count", 0),
        }

    def _tweet_to_dict(self, tweet: Tweet, source: str) -> dict:
        """
        将 Tweet 对象转换为字典

        Args:
            tweet: Tweet 对象
            source: 数据源

        Returns:
            推文字典
        """
        return {
            "tweet_id": tweet.id,
            "source": source,
            "full_text": tweet.full_text,
            "user_id": tweet.user.id,
            "user_screen_name": tweet.user.screen_name,
            "created_at": tweet.created_at,
            "url": tweet.url
        }

    def _extract_metrics(self, tweet: Tweet, source: str) -> dict:
        """
        从推文中提取 metrics 数据

        Args:
            tweet: Tweet 对象
            source: 数据源

        Returns:
            metrics 字典（符合 REQUIREMENTS.md 3.2 格式）
        """
        return {
            "post_id": tweet.id,
            "source": source,
            "repost_count": tweet.retweet_count or 0,
            "like_count": tweet.favorite_count or 0,
            "view_count": tweet.view_count or 0,
        }

    def start(
        self
    ):
        """
        启动监控循环
        """
        if schedule is None:
            raise ImportError(
                "schedule library is required. Install with: pip install schedule"
            )

        logger.info(f"Starting Community Notes Monitor...")
        logger.info(f"Task mode: {self.task_mode.value}")
        logger.info(f"Update strategy: "
                   f"new={self.config['new_interval_seconds']}s/{self.config['new_max_days']}d, "
                   f"new_to_helpful={self.config['new_to_helpful_interval_seconds']}s/{self.config['new_to_helpful_max_days']}d, "
                   f"helpful={self.config['helpful_interval_seconds']}s/{self.config['helpful_max_days']}d")
        logger.info(f"Multi-threading config: max_workers={self.config.get('max_workers', 10)}, "
                   f"fetch_parallel={self.config.get('fetch_parallel', True)}")

        self._running = True
        self._iteration = 0

        # 根据任务模式注册调度任务
        if self.task_mode in (TaskMode.CRAWL, TaskMode.ALL):
            schedule.every(self.config['note_crawl']).seconds.do(self.fetch_posts)
            logger.info(f"Registered note_crawl task (interval: {self.config['note_crawl']}s)")

        if self.task_mode in (TaskMode.UPDATE, TaskMode.ALL):
            schedule.every(self.config['metrics_update']).seconds.do(self.update_metrics_by_source, 'new')
            schedule.every(self.config['metrics_update']).seconds.do(self.update_metrics_by_source, 'helpful')
            logger.info(f"Registered metrics_update task (interval: {self.config['metrics_update']}s)")

        # 注册健康监控定时报告
        if self.health_monitor:
            health_interval = self.config.get('health_report_interval', 300)  # 默认 5 分钟
            schedule.every(health_interval).seconds.do(self.health_monitor.report)
            logger.info(f"Registered health monitor report (interval: {health_interval}s)")

        # 注册信号处理器用于优雅停止
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 运行调度循环
        while self._running:
            schedule.run_pending()
            time.sleep(1)  # 避免 CPU 空转

        # 关闭线程池
        if self._executor:
            self._executor.shutdown(wait=True)
            logger.info("Thread pool shutdown complete.")

        logger.info("Monitor stopped.")


    def _signal_handler(self, _signum, _frame):
        """处理停止信号"""
        logger.info("Received stop signal. Shutting down gracefully...")
        self._running = False
