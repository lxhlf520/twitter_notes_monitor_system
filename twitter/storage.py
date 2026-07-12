import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pymongo import MongoClient
from pymongo.collection import Collection


class Storage:
    """MongoDB 存储模块 - 支持 Community Notes 双源追踪"""

    def __init__(
        self,
        uri: str,
        database: str,
        username: Optional[str] = None,
        password: Optional[str] = None
    ):
        self.uri = uri
        self.database_name = database
        self.username = username
        self.password = password
        self._client: Optional[MongoClient] = None
        self._db = None

        # 集合：Post 双源追踪 + Notes + Contributors + 原始 API 响应
        self._new_posts: Optional[Collection] = None           # x_com_post_new
        self._new_metrics: Optional[Collection] = None         # x_com_post_new_metrics
        self._helpful_posts: Optional[Collection] = None       # x_com_post_helpful
        self._helpful_metrics: Optional[Collection] = None     # x_com_post_helpful_metrics
        self._notes: Optional[Collection] = None               # x_com_notes
        self._contributors: Optional[Collection] = None        # x_com_contributors
        self._accounts: Optional[Collection] = None            # twitter_accounts
        self._api_raw: Optional[Collection] = None             # x_com_api_raw
        self._health_snapshots: Optional[Collection] = None      # x_com_health_snapshots
        self._sig_cache: Optional[Collection] = None              # x_com_signature_cache
        self._update_status: Optional[Collection] = None          # x_com_post_update_status

    def connect(self):
        """连接 MongoDB 并初始化四个集合"""
        # 如果提供了用户名和密码，构建带认证的 URI
        if self.username and self.password:
            from urllib.parse import urlparse
            parsed = urlparse(self.uri)
            host = parsed.hostname or "localhost"
            port = parsed.port or 27017
            # 使用 admin 数据库进行认证
            auth_uri = f"mongodb://{self.username}:{self.password}@{host}:{port}/admin"
            self._client = MongoClient(auth_uri)
        else:
            # 无认证连接
            self._client = MongoClient(self.uri)

        self._db = self._client[self.database_name]

        # 初始化六个集合
        self._new_posts = self._db["x_com_post_new"]
        self._new_metrics = self._db["x_com_post_new_metrics"]
        self._helpful_posts = self._db["x_com_post_helpful"]
        self._helpful_metrics = self._db["x_com_post_helpful_metrics"]
        self._notes = self._db["x_com_notes"]
        self._contributors = self._db["x_com_contributors"]
        self._accounts = self._db["twitter_accounts"]
        self._api_raw = self._db["x_com_api_raw"]
        self._health_snapshots = self._db["x_com_health_snapshots"]
        self._sig_cache = self._db["x_com_signature_cache"]
        self._update_status = self._db["x_com_post_update_status"]

        # 自动初始化集合（确保集合存在）
        self._ensure_collections_exist()

        # 创建索引（如果权限不足则忽略，不影响正常使用）
        try:
            self._create_indexes()
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to create indexes (may require admin privileges): {e}")
            logger.warning("Continuing without indexes - query performance may be reduced")

    def _ensure_collections_exist(self):
        """确保所有集合存在（触发 MongoDB 自动创建）"""
        # 通过执行一个简单的查询来触发集合创建
        for collection_name in ["x_com_post_new", "x_com_post_new_metrics",
                                 "x_com_post_helpful", "x_com_post_helpful_metrics",
                                 "x_com_notes", "x_com_contributors",
                                 "twitter_accounts", "x_com_api_raw", "x_com_health_snapshots",
                                 "x_com_signature_cache", "x_com_post_update_status"]:
            try:
                # 使用 list_collections 检查集合是否存在
                collections = self._db.list_collection_names(filter={"name": collection_name})
                if not collections:
                    # 集合不存在，插入一个空文档来创建它（然后删除）
                    self._db[collection_name].insert_one({"_init": True})
                    self._db[collection_name].delete_one({"_init": True})
                    logger = logging.getLogger(__name__)
                    logger.info(f"Created collection: {collection_name}")
            except Exception as e:
                # 忽略权限错误，继续执行
                logging.getLogger(__name__).debug(f"Could not ensure collection {collection_name} exists: {e}")

    def _create_indexes(self):
        """创建必要的索引"""
        # 推文表的 post_id 唯一索引
        self._new_posts.create_index("post_id", unique=True)
        self._helpful_posts.create_index("post_id", unique=True)

        # metrics 表的 post_id 和 captured_at 索引
        self._new_metrics.create_index([("post_id", 1), ("captured_at", -1)])
        self._helpful_metrics.create_index([("post_id", 1), ("captured_at", -1)])

        # Notes 表的 note_id 唯一索引
        self._notes.create_index("note_id", unique=True)
        self._notes.create_index("post_id")

        # Contributors 表按 note_id 唯一（每条 note 对应一条 contributor 记录，一一对应）
        self._contributors.create_index("note_id", unique=True)
        self._contributors.create_index("author_id")

        # 账号表的 username 唯一索引和 enabled 索引
        self._accounts.create_index("username", unique=True)
        self._accounts.create_index("enabled")
        self._accounts.create_index("cooldown_until")

        # API 原始响应表索引：endpoint + 抓取时间，便于按接口检索
        self._api_raw.create_index([("endpoint", 1), ("captured_at", -1)])
        self._api_raw.create_index("post_id")

        # 健康快照表索引：按时间倒序，便于查询最新状态
        self._health_snapshots.create_index([("reported_at", -1)])
        self._health_snapshots.create_index("healthy")

        # 签名缓存表索引：按 username 查询，端点参数按 _type 查询
        self._sig_cache.create_index("username", unique=True, sparse=True)
        self._sig_cache.create_index("_type")

        # 更新状态表索引：post_id + 时间倒序，便于按推文查询更新历史
        self._update_status.create_index([("post_id", 1), ("captured_at", -1)])
        self._update_status.create_index("status")

    def close(self):
        """关闭连接"""
        if self._client:
            self._client.close()

    # ==================== New 源相关方法 ====================

    def save_new_post(self, tweet_data: Dict[str, Any]) -> Any:
        """保存 new 源的推文基础信息"""
        tweet_data["captured_at"] = datetime.utcnow()
        post_id = tweet_data.get("post_id") or tweet_data.get("tweet_id")
        if post_id:
            return self._new_posts.insert_one(tweet_data)
        raise ValueError("post_id or tweet_id is required")

    def save_new_metrics(self, metrics: Dict[str, Any]) -> Any:
        """保存 new 源的 metrics 数据（追加写入）"""
        metrics["captured_at"] = datetime.utcnow()
        return self._new_metrics.insert_one(metrics)

    def new_post_exists(self, post_id: str) -> bool:
        """检查 new 源推文是否已存在"""
        return self._new_posts.count_documents({"post_id": post_id}) > 0

    def get_new_metrics_by_tweet(self, post_id: str) -> List[Dict[str, Any]]:
        """获取 new 源某条推文的所有历史 metrics"""
        cursor = self._new_metrics.find({"post_id": post_id}).sort("captured_at", 1)
        return list(cursor)

    # ==================== Helpful 源相关方法 ====================

    def save_helpful_post(self, tweet_data: Dict[str, Any]) -> Any:
        """保存 helpful 源的推文基础信息"""
        tweet_data["captured_at"] = datetime.utcnow()
        post_id = tweet_data.get("post_id") or tweet_data.get("tweet_id")
        if post_id:
            return self._helpful_posts.insert_one(tweet_data)
        raise ValueError("post_id or tweet_id is required")

    def save_helpful_metrics(self, metrics: Dict[str, Any]) -> Any:
        """保存 helpful 源的 metrics 数据（追加写入）"""
        metrics["captured_at"] = datetime.utcnow()
        return self._helpful_metrics.insert_one(metrics)

    def helpful_post_exists(self, post_id: str) -> bool:
        """检查 helpful 源推文是否已存在"""
        return self._helpful_posts.count_documents({"post_id": post_id}) > 0

    def is_new_post_become_helpful(self, post_id: str) -> bool:
        """检查 new 源的推文是否已变成 helpful note"""
        return self._helpful_posts.count_documents({"post_id": post_id}) > 0

    def get_helpful_metrics_by_tweet(self, post_id: str) -> List[Dict[str, Any]]:
        """获取 helpful 源某条推文的所有历史 metrics"""
        cursor = self._helpful_metrics.find({"post_id": post_id}).sort("captured_at", 1)
        return list(cursor)

    # ==================== 通用方法 ====================

    def get_all_tracked_posts(self, source: str) -> List[Dict[str, Any]]:
        """
        获取某源的所有追踪推文

        Args:
            source: 数据源，'new' 或 'helpful'

        Returns:
            推文列表
        """
        if source == 'new':
            cursor = self._new_posts.find({})
        else:
            cursor = self._helpful_posts.find({})
        return list(cursor)

    def get_last_metrics_time(self, tweet_id: str, source: str) -> Optional[datetime]:
        """
        获取某条推文上次更新 metrics 的时间

        Args:
            tweet_id: 推文 ID
            source: 数据源，'new' 或 'helpful'

        Returns:
            上次更新时间，如果没有则返回 None
        """
        if source == 'new':
            collection = self._new_metrics
        else:
            collection = self._helpful_metrics

        result = collection.find_one(
            {"tweet_id": tweet_id},
            sort=[("captured_at", -1)],
            projection={"captured_at": 1, "_id": 0}
        )

        if result:
            return result.get("captured_at")
        return None

    def get_posts_needing_update(
        self,
        source: str,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        根据双源独立更新策略获取需要更新的推文列表

        策略说明：
        - new note: 每 new_interval_seconds 秒更新，最多追踪 new_max_days 天
        - new note 变成 helpful: 每 new_to_helpful_interval_seconds 秒更新，最多追踪 new_to_helpful_max_days 天
        - helpful note: 每 helpful_interval_seconds 秒更新，最多追踪 helpful_max_days 天

        Args:
            source: 数据源，'new' 或 'helpful'
            config: 更新频率配置

        Returns:
            需要更新的推文列表
        """
        now = datetime.utcnow()

        # 获取对应源的所有推文
        if source == 'new':
            collection = self._new_posts
            metrics_collection = self._new_metrics
        else:
            collection = self._helpful_posts
            metrics_collection = self._helpful_metrics

        all_posts = list(collection.find({"deleted_at": {"$exists": False}}))
        posts_to_update = []

        for post in all_posts:
            post_id = post.get('post_id') or post.get('tweet_id')
            captured_at = post.get('captured_at', now)
            if isinstance(captured_at, (int, float)):
                captured_at = datetime.utcfromtimestamp(captured_at / 1000)
            age_days = (now - captured_at).days

            # 根据源类型决定更新策略
            if source == 'new':
                # 检查是否已超过最大追踪天数（14天）
                max_days = config.get('new_to_helpful_max_days', 14)
                if age_days > max_days:
                    # 超过最大追踪天数，停止更新
                    continue

                # 检查是否已变成 helpful
                is_helpful = self.is_new_post_become_helpful(post_id)

                if is_helpful:
                    # 已变成 helpful，使用 new_to_helpful 策略
                    interval_seconds = config.get('new_to_helpful_interval_seconds', 7200)
                else:
                    # 未变成 helpful，使用 new 策略
                    interval_seconds = config.get('new_interval_seconds', 14400)
                    # 未变成 helpful 最多只追踪 new_max_days 天
                    new_max_days = config.get('new_max_days', 6)
                    if age_days > new_max_days:
                        # 超过 new_max_days 且未变成 helpful，停止更新
                        continue

            else:  # source == 'helpful'
                # helpful note 策略
                max_days = config.get('helpful_max_days', 14)
                if age_days > max_days:
                    # 超过最大追踪天数，停止更新
                    continue
                interval_seconds = config.get('helpful_interval_seconds', 7200)

            # 检查上次更新时间
            last_metrics = metrics_collection.find_one(
                {"post_id": post_id},
                sort=[("captured_at", -1)],
                projection={"captured_at": 1, "_id": 0}
            )

            # 如果没有 metrics 记录，或者距离上次更新已超过间隔，则需要更新
            needs_update = False
            if last_metrics is None:
                needs_update = True
            else:
                last_captured_at = last_metrics['captured_at']
                if isinstance(last_captured_at, (int, float)):
                    last_captured_at = datetime.utcfromtimestamp(last_captured_at / 1000)
                time_since_update = (now - last_captured_at).total_seconds()
                if time_since_update >= interval_seconds:
                    needs_update = True

            if not needs_update:
                # 失败回补：如果最近一次更新状态是 "failed"，立即重试
                # 避免因账号池耗尽等临时故障导致掉队
                last_update = self._update_status.find_one(
                    {"post_id": post_id},
                    sort=[("captured_at", -1)],
                    projection={"status": 1, "_id": 0}
                )
                if last_update and last_update.get("status") == "failed":
                    needs_update = True

            if needs_update:
                posts_to_update.append(post)

        return posts_to_update

    # ==================== Notes 和 Contributors 相关方法 ====================

    def save_notes(self, notes: List[Dict[str, Any]]) -> int:
        """
        批量保存 Note 信息（插入后不更新）

        Args:
            notes: Note 列表

        Returns:
            实际插入的 Note 数量
        """
        inserted = 0
        for note in notes:
            if not self.note_exists(note.get("note_id", "")):
                self._notes.insert_one(note)
                inserted += 1
        return inserted

    def save_contributors(self, contributors: List[Dict[str, Any]]) -> int:
        """
        批量保存 Contributor 信息（按 note_id 去重，每条 note 对应一条 contributor 记录）

        Args:
            contributors: Contributor 列表

        Returns:
            实际插入的 Contributor 数量
        """
        inserted = 0
        for contributor in contributors:
            note_id = contributor.get("note_id", "")
            if note_id and not self.contributor_exists(note_id):
                self._contributors.insert_one(contributor)
                inserted += 1
        return inserted

    def note_exists(self, note_id: str) -> bool:
        """检查 Note 是否已存在"""
        return self._notes.count_documents({"note_id": note_id}) > 0

    def contributor_exists(self, note_id: str) -> bool:
        """检查 Contributor 是否已存在（按 note_id 一一对应）"""
        return self._contributors.count_documents({"note_id": note_id}) > 0

    # ==================== 账号池相关方法 ====================

    def save_account(self, account_data: Dict[str, Any]) -> Any:
        """保存账号信息"""
        # 确保集合存在（自动初始化）
        self._ensure_collection_exists()

        account_data["updated_at"] = datetime.utcnow()
        return self._accounts.insert_one(account_data)

    def _ensure_collection_exists(self):
        """确保 twitter_accounts 集合存在，如果不存在则创建"""
        if self._accounts is None:
            self._accounts = self._db["twitter_accounts"]

        # 检查集合是否存在，不存在则创建一个空文档来触发集合创建
        try:
            self._db.command("collstats", "twitter_accounts")
        except Exception:
            # 集合不存在，尝试创建一个空文档来初始化集合
            try:
                self._accounts.insert_one({"_placeholder": True})
                self._accounts.delete_one({"_placeholder": True})
            except Exception as e:
                # 如果是因为权限不足，继续执行，后续的 insert 可能会失败
                logging.getLogger(__name__).debug(f"Could not pre-create collection: {e}")

    def get_account(self, username: str) -> Optional[Dict[str, Any]]:
        """获取单个账号信息"""
        return self._accounts.find_one({"username": username})

    def get_next_available_account(self, last_used_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取下一个可用账号（轮询模式）

        Args:
            last_used_username: 上次使用的账号用户名，用于轮询

        Returns:
            可用账号，如果没有可用账号则返回 None
        """
        now = datetime.utcnow()

        # 查询可用账号：启用状态且冷却时间已过
        query = {
            "enabled": True,
            "$or": [
                {"cooldown_until": None},
                {"cooldown_until": {"$lt": now}}
            ]
        }

        # 获取所有可用账号
        available_accounts = list(self._accounts.find(query).sort("_id", 1))

        if not available_accounts:
            return None

        # 如果没有指定上次使用的账号，返回第一个
        if last_used_username is None:
            return available_accounts[0]

        # 找到上次使用的账号在列表中的位置，返回下一个（循环）
        for i, account in enumerate(available_accounts):
            if account["username"] == last_used_username:
                # 返回下一个账号（循环到开头）
                next_index = (i + 1) % len(available_accounts)
                return available_accounts[next_index]

        # 如果上次使用的账号不在可用列表中，返回第一个
        return available_accounts[0]

    def update_account_stats(
        self,
        username: str,
        success: Optional[bool] = None,
        error: Optional[str] = None,
        cooldown_until: Optional[datetime] = None
    ) -> None:
        """
        更新账号统计信息

        Args:
            username: 账号用户名
            success: 是否成功（True/False/None）
            error: 错误信息（失败时）
            cooldown_until: 冷却截止时间
        """
        update_data = {
            "last_used_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        if success is True:
            update_data["$inc"] = {"request_count": 1, "success_count": 1}
        elif success is False:
            update_data["$inc"] = {"request_count": 1, "fail_count": 1}
            if error:
                update_data["last_error"] = error

        if cooldown_until:
            update_data["cooldown_until"] = cooldown_until

        # 构建更新操作
        update_op = {"$set": update_data}
        if "$inc" in update_op["$set"]:
            inc_data = update_op["$set"].pop("$inc")
            update_op["$inc"] = inc_data

        self._accounts.update_one({"username": username}, update_op)

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """获取所有账号"""
        return list(self._accounts.find({}).sort("_id", 1))

    def mark_account_enabled(self, username: str, enabled: bool) -> None:
        """手动启用/禁用账号"""
        self._accounts.update_one(
            {"username": username},
            {"$set": {"enabled": enabled, "updated_at": datetime.utcnow()}}
        )

    def update_account_from_model(self, account: Any) -> None:
        """
        从 Pydantic Account 模型更新账号到数据库

        Args:
            account: Account Pydantic 模型实例
        """
        # 使用 duck typing 避免循环导入
        # 只要对象有所需的字段即可
        if not hasattr(account, 'username') or not hasattr(account, 'to_dict'):
            raise TypeError("Expected object with username and to_dict method")

        update_data = account.to_dict()
        # 移除不需要更新的字段
        update_data.pop("username", None)  # username 作为查询条件
        update_data["updated_at"] = datetime.utcnow()

        self._accounts.update_one(
            {"username": account.username},
            {"$set": update_data}
        )

    # ==================== 原始 API 响应相关方法 ====================

    def save_api_response(
        self,
        endpoint: str,
        response: Any,
        params: Optional[Dict[str, Any]] = None,
        post_id: Optional[str] = None,
    ) -> Any:
        """
        保存接口原始响应到 x_com_api_raw 集合

        Args:
            endpoint: 接口名称（如 TweetDetail / GenericTimeline / BirdwatchFetchGlobalTimeline）
            response: 原始响应内容（dict / list / str），按原样落库
            params: 调用时的请求参数（用于排查/重放）
            post_id: 可选关联的推文 ID，便于按推文检索原始数据

        Returns:
            insert_one 的结果对象
        """
        if self._api_raw is None:
            return None

        doc: Dict[str, Any] = {
            "endpoint": endpoint,
            "captured_at": datetime.utcnow(),
            "response": response,
        }
        if params is not None:
            doc["params"] = params
        if post_id is not None:
            doc["post_id"] = post_id

        try:
            return self._api_raw.insert_one(doc)
        except Exception as e:
            # 持久化失败不应影响主流程
            logging.getLogger(__name__).warning(
                f"Failed to save raw API response for {endpoint}: {e}"
            )
            return None

    # ==================== 健康快照相关方法 ====================

    def save_health_snapshot(self, snapshot: Dict[str, Any]) -> Any:
        """
        保存健康快照到 x_com_health_snapshots 集合

        Args:
            snapshot: HealthMonitor.report() 返回的快照字典

        Returns:
            insert_one 的结果对象
        """
        if self._health_snapshots is None:
            return None

        try:
            return self._health_snapshots.insert_one(snapshot)
        except Exception as e:
            logging.getLogger(__name__).debug(f"Failed to save health snapshot: {e}")
            return None

    def get_latest_health_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        获取最近一次健康快照

        Returns:
            最新的健康快照字典，如果没有则返回 None
        """
        if self._health_snapshots is None:
            return None

        return self._health_snapshots.find_one(
            {},
            sort=[("reported_at", -1)]
        )

    def get_health_snapshots(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取指定时间范围内的健康快照

        Args:
            hours: 查询最近多少小时的快照
            limit: 最多返回的记录数

        Returns:
            健康快照列表
        """
        if self._health_snapshots is None:
            return []

        cutoff = datetime.utcnow() - timedelta(hours=hours)
        cursor = self._health_snapshots.find(
            {"reported_at": {"$gte": cutoff.isoformat()}},
            sort=[("reported_at", -1)],
            limit=limit
        )
        return list(cursor)

    # ==================== 签名缓存相关方法 ====================

    def save_signature_cache(self, username: str, cache_data: Dict[str, Any]) -> None:
        """
        保存账号的签名材料缓存

        Args:
            username: 账号用户名
            cache_data: 缓存数据（key_bytes, key_byte_indices, arr_2d）
        """
        cache_data["username"] = username
        cache_data["updated_at"] = datetime.utcnow()
        self._sig_cache.update_one(
            {"username": username},
            {"$set": cache_data},
            upsert=True
        )

    def get_signature_cache(self, username: str) -> Optional[Dict[str, Any]]:
        """
        获取账号的签名材料缓存

        Args:
            username: 账号用户名

        Returns:
            缓存数据字典，未找到时返回 None
        """
        return self._sig_cache.find_one({"username": username})

    def delete_signature_cache(self, username: str) -> None:
        """删除账号的签名材料缓存（签名失效时调用）"""
        self._sig_cache.delete_one({"username": username})

    # ==================== 端点参数缓存相关方法 ====================

    def save_endpoint_params(self, params: Dict[str, Any]) -> None:
        """
        保存 GraphQL 端点参数缓存（全局共享，所有账号通用）

        Args:
            params: endpoint_params 字典
        """
        self._sig_cache.update_one(
            {"_type": "endpoint_params"},
            {"$set": {
                "_type": "endpoint_params",
                "params": params,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )

    def get_endpoint_params(self) -> Optional[Dict[str, Any]]:
        """
        获取缓存的 GraphQL 端点参数

        Returns:
            endpoint_params 字典，未找到时返回 None
        """
        doc = self._sig_cache.find_one({"_type": "endpoint_params"})
        if doc:
            return doc.get("params")
        return None

    # ==================== 更新状态记录相关方法 ====================

    def save_update_record(self, post_id: str, source: str, status: str,
                           error: Optional[str] = None,
                           metrics: Optional[Dict[str, Any]] = None) -> None:
        """
        记录一条推文指标的更新状态到 x_com_post_update_status 集合。

        Args:
            post_id: 推文 ID
            source: 数据源（new / helpful）
            status: 状态（success / failed / deleted）
            error: 失败时的错误信息
            metrics: 成功时的指标快照
        """
        record = {
            "post_id": post_id,
            "source": source,
            "status": status,
            "captured_at": datetime.utcnow(),
        }
        if error:
            record["error"] = error
        if metrics:
            record["metrics"] = metrics

        try:
            self._update_status.insert_one(record)
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Failed to save update record for {post_id}: {e}"
            )

    def get_post_update_records(self, post_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取某条推文最近的更新记录。

        Args:
            post_id: 推文 ID
            limit: 最大返回条数

        Returns:
            更新记录列表（按时间倒序）
        """
        cursor = self._update_status.find(
            {"post_id": post_id},
            sort=[("captured_at", -1)],
            limit=limit
        )
        return list(cursor)

    def get_post_update_summary(self, post_id: str) -> Dict[str, Any]:
        """
        获取某条推文的更新状态摘要（最近 N 次的成功/失败统计）。

        Returns:
            {
                "post_id": str,
                "total_updates": int,
                "success_count": int,
                "failed_count": int,
                "last_status": str | None,
                "last_error": str | None,
                "is_deleted": bool,
            }
        """
        records = self.get_post_update_records(post_id, limit=100)
        total = len(records)
        success_count = sum(1 for r in records if r.get("status") == "success")
        failed_count = sum(1 for r in records if r.get("status") in ("failed", "deleted"))
        last_record = records[0] if records else None

        return {
            "post_id": post_id,
            "total_updates": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "last_status": last_record.get("status") if last_record else None,
            "last_error": last_record.get("error") if last_record else None,
            "is_deleted": any(r.get("status") == "deleted" for r in records),
        }

    # ==================== 推文删除标记相关方法 ====================

    def mark_post_deleted(self, post_id: str, source: str) -> bool:
        """
        将某条推文标记为已删除（在对应源的 post 集合中设置 deleted_at 字段）。

        Args:
            post_id: 推文 ID
            source: 数据源（new / helpful）

        Returns:
            True 表示标记成功，False 表示推文不存在或已标记过
        """
        if source == 'new':
            collection = self._new_posts
        else:
            collection = self._helpful_posts

        result = collection.update_one(
            {"post_id": post_id, "deleted_at": {"$exists": False}},
            {"$set": {"deleted_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    def get_active_posts(self, source: str) -> List[Dict[str, Any]]:
        """
        获取指定源中未被删除的推文列表。

        Args:
            source: 数据源（new / helpful）

        Returns:
            活跃推文列表
        """
        if source == 'new':
            collection = self._new_posts
        else:
            collection = self._helpful_posts

        cursor = collection.find({"deleted_at": {"$exists": False}})
        return list(cursor)
