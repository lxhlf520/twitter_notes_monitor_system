from __future__ import annotations
import json
import logging
import random
import threading
import time
import signal
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
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
        account_pool: Any = None,
    ):
        """
        初始化监控器

        Args:
            client: Twitter API 客户端
            storage: 存储器
            config: 更新频率配置，默认为 None 时使用默认值
            task_mode: 任务运行模式，默认为 ALL（同时运行两个任务）
            health_monitor: 健康监控器实例，如果为 None 则不进行健康监控
            account_pool: AccountPool 实例（用于运行时同步新增账号）
        """
        self.client = client
        self.storage = storage
        self.task_mode = task_mode
        self.health_monitor = health_monitor
        self.account_pool = account_pool

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
            'max_workers': 10,
            'fetch_parallel': True,
            # 账号同步配置
            'account_sync_interval': 21600,         # 6小时同步一次新增账号
        }

        if config:
            default_config.update(config)

        self.config = default_config

        # 独立线程池，各任务互不干扰
        max_workers = self.config.get('max_workers', 10)
        crawl_workers = self.config.get('crawl_workers', max(2, max_workers // 2))
        update_new_workers = self.config.get('update_new_workers', max_workers)
        update_helpful_workers = self.config.get('update_helpful_workers', max_workers)
        self._crawl_executor = ThreadPoolExecutor(max_workers=crawl_workers)
        self._update_executors = {
            'new': ThreadPoolExecutor(max_workers=update_new_workers),
            'helpful': ThreadPoolExecutor(max_workers=update_helpful_workers),
        }

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
            # 首次保存时设置初始 next_update_at
            init_metrics = self._extract_metrics(tweet, source)
            init_next = self._calc_next_update_at(
                {"tweet_id": tweet.id}, source
            )
            if init_next:
                init_metrics['next_update_at'] = init_next

            if source == "helpful" and not self.storage.helpful_post_exists(tweet.id):
                # 保存 Post 静态信息
                post_data = self._tweet_to_post_data(tweet, 'helpful')
                self.storage.save_helpful_post(post_data)
                # 保存初始 Metrics（含动态间隔）
                self.storage.save_helpful_metrics(init_metrics)
                self._save_note_and_contributors(tweet)
                new_count += 1
                logger.info(f"[HELPFUL] Captured tweet: {tweet.id}")
            elif source == "new" and not self.storage.new_post_exists(tweet.id):
                # self.storage.save_new_post(self._tweet_to_dict(tweet, source))
                post_data = self._tweet_to_post_data(tweet, 'new')
                self.storage.save_new_post(post_data)
                # 保存初始 Metrics（含动态间隔）
                self.storage.save_new_metrics(init_metrics)
                # 获取并保存 Note/Contributor 信息
                self._save_note_and_contributors(tweet)
                helpful_count += 1
                logger.info(f"[NEW] Captured tweet: {tweet.id}")
    
        try:
            # communitynotes_rated_helpful 返回包含两个源的字典
            result = self.client.communitynotes_rated_helpful()

            helpful: List[Tweet] = result.get('rated_helpful', []) or []
            new: List[Tweet] = result.get('new', []) or []

            futures = {
                self._crawl_executor.submit(save_post, tweet, 'helpful'): 'helpful'
                for tweet in helpful
            } | {
                self._crawl_executor.submit(save_post, tweet, 'new'): 'new'
                for tweet in new
            }
            for future in as_completed(futures):
                if future.exception():
                    logger.error(
                        f"Error processing tweet: {future.exception()}",
                        exc_info=future.exception(),
                    )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"

            # 账号池耗尽降级为警告，避免误报任务失败
            if "No available accounts" in str(e):
                logger.warning(f"账号池暂无可用，推迟抓取（将在下个周期重试）")
                return {"new_posts": 0, "helpful_posts": 0, "errors": []}

            # 429 限流是账号级别问题，降级为警告
            if "TooManyRequests" in type(e).__name__:
                logger.warning(f"账号限流，推迟抓取（将在下个周期重试）")
                return {"new_posts": 0, "helpful_posts": 0, "errors": []}

            # TweetNotAvailable 是服务端返回的超时/不可见等临时错误
            if "TweetNotAvailable" in type(e).__name__:
                logger.warning(f"推文列表暂时不可用，推迟抓取（将在下个周期重试）")
                return {"new_posts": 0, "helpful_posts": 0, "errors": []}

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
    
    

    def _save_note_and_contributors(self, tweet: Tweet) -> None:
        """
        获取并保存特定推文的 Note 和 Contributor 信息

        Args:
            tweet: Tweet 对象（从 _data 中提取 Notes，无需额外 API 调用）
        """
        try:
            note_data = self.client.communitynotes_detail(tweet.id, tweet._data)
            if note_data:
                # 保存 Notes
                self.storage.save_notes(note_data['notes'])
                # 保存 Contributors
                self.storage.save_contributors(note_data['contributors'])
                logger.info(f"Saved {len(note_data['notes'])} notes for tweet {tweet.id}")
        except Exception as e:
            logger.debug(f"Failed to fetch notes for tweet {tweet.id}: {e}")

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

                        # 动态间隔：计算下次更新的随机时间并写 metrics 字段
                        next_update_at = self._calc_next_update_at(post, source)
                        if next_update_at:
                            metrics['next_update_at'] = next_update_at

                        if source == 'new':
                            self.storage.save_new_metrics(metrics)
                        else:
                            self.storage.save_helpful_metrics(metrics)

                        # 记录更新成功
                        self.storage.save_update_record(
                            post_id, source, "success",
                            metrics=metrics
                        )

                        return True
                    else:
                        # 推文不存在（已删除/不可见），标记并记录
                        logger.warning(f"推文 {post_id} 不存在（可能已删除），正在标记...")
                        self.storage.mark_post_deleted(post_id, source)
                        self.storage.save_update_record(
                            post_id, source, "deleted",
                            error="Tweet not found (possibly deleted)"
                        )
                        return False

                except Exception as e:
                    pid = post.get('post_id') or post.get('tweet_id', 'unknown')
                    error_msg = f"{type(e).__name__}: {e}"

                    # 账号池耗尽不是推文级别的错误，降级日志
                    if "No available accounts" in str(e):
                        logger.warning(f"账号池暂无可用，推迟更新 {pid}（将在下个周期重试）")
                        # 需要记录失败状态以触发回补机制
                        try:
                            self.storage.save_update_record(
                                pid, source, "failed",
                                error="No available accounts"
                            )
                        except Exception:
                            pass
                        return False

                    # 429 限流是账号级别问题（已强制冷却 60s），不记推文失败
                    if "TooManyRequests" in type(e).__name__:
                        logger.warning(f"账号限流，推迟更新 {pid}（账号已冷却 60s）")
                        return False

                    # TweetNotAvailable 是 Twitter 服务端返回的错误（超时/不可见等），非推文永久缺失
                    # 不回补状态，让自然周期重试；连续多次后 `get_tweet_by_id` 返回 None 才会标记已删除
                    if "TweetNotAvailable" in type(e).__name__:
                        logger.warning(f"推文暂时不可用，推迟更新 {pid}（{error_msg}）")
                        return False

                    logger.error(
                        f"Failed to update {pid}: {error_msg}",
                        exc_info=True,
                    )
                    errors.append(f"Failed to update {pid}: {error_msg}")

                    # 记录更新失败
                    try:
                        self.storage.save_update_record(
                            pid, source, "failed",
                            error=error_msg
                        )
                    except Exception:
                        pass

                    return False

            # 使用类属性线程池并发更新
            future_to_post = {
                self._update_executors[source].submit(update_single_post, post): post
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
            "captured_at": datetime.utcnow(),
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

    def _calc_next_update_at(self, post: dict, source: str) -> Optional[datetime]:
        """
        根据配置的动态间隔范围 [min, max] 计算下次更新的随机时间。
        将大量 post 的到期时间在时间轴上自然摊开，避免集中争抢账号。

        Args:
            post: 推文字典
            source: 数据源（'new' / 'helpful'）

        Returns:
            下次更新时间（UTC），如果未配置动态间隔则返回 None
        """
        config = self.config
        post_id = post.get('post_id') or post.get('tweet_id')

        if source == 'new':
            # new 源：根据是否已变成 helpful 选择不同范围
            is_helpful = self.storage.is_new_post_become_helpful(post_id)
            if is_helpful:
                min_sec = config.get('new_to_helpful_min_seconds')
                max_sec = config.get('new_to_helpful_max_seconds')
            else:
                min_sec = config.get('new_min_seconds')
                max_sec = config.get('new_max_seconds')
        else:
            min_sec = config.get('helpful_min_seconds')
            max_sec = config.get('helpful_max_seconds')

        if min_sec is None or max_sec is None:
            # 未配置动态间隔，回退到固定间隔
            return None

        interval = random.randint(min_sec, max_sec)
        next_time = datetime.utcnow() + timedelta(seconds=interval)
        return next_time


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
                   f"crawl={self.config.get('crawl_workers', 'auto')}, "
                   f"update_new={self.config.get('update_new_workers', 'auto')}, "
                   f"update_helpful={self.config.get('update_helpful_workers', 'auto')}, "
                   f"fetch_parallel={self.config.get('fetch_parallel', True)}")

        self._running = True
        self._iteration = 0

        # 根据任务模式注册调度任务，加入初始偏移避免同时抢账号
        if self.task_mode in (TaskMode.CRAWL, TaskMode.ALL):
            schedule.every(self.config['note_crawl']).seconds.do(self.fetch_posts)
            logger.info(f"Registered note_crawl task (interval: {self.config['note_crawl']}s)")

        if self.task_mode in (TaskMode.UPDATE, TaskMode.ALL):
            # update_new 延迟 3s 启动，避免与 crawl 同时抢账号
            def _register_update_new():
                schedule.every(self.config['metrics_update']).seconds.do(
                    self.update_metrics_by_source, 'new'
                )
            threading.Timer(3, _register_update_new).start()

            # update_helpful 延迟 6s 启动，进一步错峰
            def _register_update_helpful():
                schedule.every(self.config['metrics_update']).seconds.do(
                    self.update_metrics_by_source, 'helpful'
                )
            threading.Timer(6, _register_update_helpful).start()
            logger.info(f"Registered stagger metrics_update tasks (interval: {self.config['metrics_update']}s, offset 3s/6s)")

        # 注册健康监控定时报告
        if self.health_monitor:
            health_interval = self.config.get('health_report_interval', 300)  # 默认 5 分钟
            schedule.every(health_interval).seconds.do(self.health_monitor.report)
            logger.info(f"Registered health monitor report (interval: {health_interval}s)")

        # 注册账号池同步（非 RPC 模式且传入了 account_pool）
        if self.account_pool:
            sync_interval = self.config.get('account_sync_interval', 21600)
            schedule.every(sync_interval).seconds.do(self.account_pool.sync_accounts_from_db)
            logger.info(f"Registered account sync task (interval: {sync_interval}s = {sync_interval // 3600}h)")

        # 注册信号处理器用于优雅停止
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 运行调度循环
        while self._running:
            schedule.run_pending()
            time.sleep(1)  # 避免 CPU 空转

        # 关闭所有线程池
        for name, executor in [('crawl', self._crawl_executor)] + list(self._update_executors.items()):
            if executor:
                executor.shutdown(wait=True)
                logger.info(f"{name} thread pool shutdown complete.")

        logger.info("Monitor stopped.")


    def _signal_handler(self, _signum, _frame):
        """处理停止信号"""
        logger.info("Received stop signal. Shutting down gracefully...")
        self._running = False
