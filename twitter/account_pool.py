from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from .storage import Storage
from .utils import cookie_str_to_dict, cookie_dict_to_str
from curl_cffi.requests import Session
from bs4 import BeautifulSoup
from .x_client_transaction import ClientTransaction
import re
import base64
import logging

logger = logging.getLogger(__name__)


class Account(BaseModel):
    """账号数据模型"""
    username: str
    cookie: str
    enabled: bool = True
    last_used_at: Optional[datetime] = None
    request_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_error: Optional[str] = None
    cooldown_until: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    def is_available(self) -> bool:
        """检查账号是否可用"""
        if not self.enabled:
            return False
        if self.cooldown_until and datetime.utcnow() < self.cooldown_until:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于数据库存储）"""
        return self.model_dump()


class AccountSession:
    """每个账号独立的 HTTP Session 上下文，封装 curl_cffi Session、cookies 和 ClientTransaction 签名"""

    def __init__(self, account: Account, proxy: str | None = None, storage: Optional[Storage] = None) -> None:
        self.account = account
        self.storage = storage
        self.http = Session(proxy=proxy, impersonate="chrome131")
        if isinstance(account.cookie, str):
            self.cookies = account.cookie
            self.cookies_dict = cookie_str_to_dict(account.cookie)
        else:
            self.cookies_dict = account.cookie
            self.cookies = cookie_dict_to_str(account.cookie)

        # 将 cookies 设置到 curl_cffi Session，后续请求自动携带
        for name, value in self.cookies_dict.items():
            self.http.cookies.set(name, value, domain=".x.com")
        
        # 初始化时将 auth headers 设置到 Session 默认 headers，后续请求自动携带
        self._setup_auth_headers()

        # ClientTransaction 延迟初始化（首次调用 ensure_client_transaction 时获取）
        self.client_transaction = None

    def _setup_auth_headers(self) -> None:
        """将 CSRF token 设置到 Session 默认 headers 中。

        guest_token (gt) 不是浏览器 cookie，不在这里强制校验；
        如果 cookie 中有 gt 则带上，没有则由后续调用方按需获取。
        """
        from .errors import TwitterException

        csrf_token = self.get_csrf_token()
        if csrf_token is None:
            raise TwitterException(f"Account '{self.account.username}' does not have a valid CSRF token")

        self.http.headers['X-Csrf-Token'] = csrf_token

        guest_token = self.get_guest_token()
        if guest_token:
            self.http.headers['x-guest-token'] = guest_token

    def get_csrf_token(self) -> str | None:
        return self.cookies_dict.get('ct0')

    def get_guest_token(self) -> str | None:
        return self.cookies_dict.get("gt")

    def ensure_client_transaction(self) -> bool:
        """
        确保当前 Session 拥有可用的 ClientTransaction 实例。
        优先从缓存恢复，缓存不存在则通过 HTTP 从 x.com 获取。

        Returns:
            True 表示初始化成功，False 表示失败
        """
        if self.client_transaction is not None:
            return True

        # 1. 尝试从缓存恢复
        if self.storage:
            cached = self.storage.get_signature_cache(self.account.username)
            if cached and all(k in cached for k in ['key_bytes', 'key_byte_indices', 'arr_2d']):
                try:
                    self.client_transaction = ClientTransaction.from_cache(
                        cached['key_bytes'],
                        cached['key_byte_indices'],
                        cached['arr_2d']
                    )
                    logger.info(f"[{self.account.username}] 签名材料从缓存恢复")
                    return True
                except Exception as e:
                    logger.warning(f"[{self.account.username}] 缓存签名恢复失败: {e}，重新获取")

        # 2. 缓存未命中，从 x.com 获取
        return self._fetch_signature_materials()

    def _fetch_signature_materials(self) -> bool:
        """
        通过直接 HTTP 请求从 x.com 获取签名材料（无需浏览器）。
        获取后自动缓存到 MongoDB。
        """
        try:
            logger.info(f"[{self.account.username}] 正在从 x.com 获取签名材料...")
            resp = self.http.get('https://x.com/', timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 2b. 提取 key_bytes
            element = soup.select_one("[name='twitter-site-verification']")
            if not element:
                logger.error(f"[{self.account.username}] 页面中未找到 twitter-site-verification meta 标签")
                return False
            key_bytes = list(base64.b64decode(element.get("content").encode('utf-8')))

            # 2c. 提取 2D array
            frames = soup.select("[id^='loading-x-anim']")
            if not frames:
                logger.error(f"[{self.account.username}] 页面中未找到 loading-x-anim 元素")
                return False
            row_idx = key_bytes[5] % 4 if len(key_bytes) > 5 else 0
            d_attr = list(list(frames[row_idx].children)[0].children)[1].get("d", "")
            arr_2d = [
                [int(x) for x in re.sub(r"[^\d]+", " ", item).strip().split()]
                for item in d_attr[9:].split("C")
            ]

            # 2d. 查找并下载 ondemand.js 提取 key_byte_indices
            key_byte_indices = self._extract_key_byte_indices(soup)
            if not key_byte_indices:
                logger.error(f"[{self.account.username}] 无法从 ondemand.js 提取 key_byte_indices")
                return False

            # 2e. 构造 ClientTransaction
            self.client_transaction = ClientTransaction.from_cache(
                key_bytes, key_byte_indices, arr_2d
            )

            # 2f. 缓存到 MongoDB
            if self.storage:
                self.storage.save_signature_cache(self.account.username, {
                    "key_bytes": key_bytes,
                    "key_byte_indices": key_byte_indices,
                    "arr_2d": arr_2d,
                })
                logger.info(f"[{self.account.username}] 签名材料已缓存到 MongoDB")

            logger.info(f"[{self.account.username}] 签名材料获取完成")
            return True

        except Exception as e:
            logger.error(f"[{self.account.username}] 获取签名材料失败: {type(e).__name__}: {e}")
            return False

    def _extract_key_byte_indices(self, soup: BeautifulSoup) -> Optional[List[int]]:
        """
        从页面 HTML 中找到 ondemand.js URL，下载并提取 key_byte_indices。
        """
        try:
            # 查找 ondemand.js URL：优先从 link preload 查找
            ondemand_url = None
            for link in soup.select('link[as="script"][href*="ondemand"]'):
                ondemand_url = link.get('href')
                break

            # 其次从 script 查找
            if not ondemand_url:
                for script in soup.select('script[src*="ondemand"]'):
                    ondemand_url = script.get('src')
                    break

            if not ondemand_url:
                # 从 main.js URL 推导：main.XYZ.js → ondemand.s.XYZ.js
                for script in soup.select('script[src]'):
                    src = script.get('src', '')
                    if '/main.' in src and src.endswith('.js'):
                        ondemand_url = src.replace('/main.', '/ondemand.s.')
                        break

            if not ondemand_url:
                return None

            # 补全 URL
            if ondemand_url.startswith('//'):
                ondemand_url = 'https:' + ondemand_url
            elif ondemand_url.startswith('/'):
                ondemand_url = 'https://x.com' + ondemand_url

            # 下载 ondemand.js
            ondemand_resp = self.http.get(ondemand_url, timeout=30)
            ondemand_content = ondemand_resp.text

            # 提取 key_byte_indices
            INDICES_REGEX = re.compile(r"\(\w{1}\[(\d{1,2})\],\s*16\)")
            key_byte_indices = [
                int(m.group(1)) for m in INDICES_REGEX.finditer(ondemand_content)
            ]
            return key_byte_indices

        except Exception as e:
            logger.warning(f"提取 key_byte_indices 失败: {e}")
            return None

    def generate_transaction_id(self, method: str, path: str) -> str:
        """
        使用当前 Session 的 ClientTransaction 生成请求签名 Transaction ID。

        Args:
            method: HTTP 方法（GET/POST）
            path: URL 路径

        Returns:
            签名字符串
        """
        if self.client_transaction is None:
            return ''
        return self.client_transaction.generate_transaction_id(method=method, path=path)

    def verify_account(self) -> Optional[bool]:
        """
        通过请求 x.com 首页验证 cookie 是否有效。
        返回 200 且页面包含 'gt='（已登录特征）则判定有效。

        Returns:
            True  = cookie 有效
            False = cookie 已失效（需禁用账号）
            None  = 网络异常，不确定
        """
        try:
            headers = {
                'User-Agent': self.http.headers.get('User-Agent', ''),
                'X-Csrf-Token': self.get_csrf_token() or '',
            }
            resp = self.http.get(
                'https://x.com/',
                headers=headers,
                timeout=15
            )
            if resp.status_code == 200:
                return True
            elif resp.status_code in (401, 403):
                logger.warning(f"[{self.account.username}] Cookie 已失效 (HTTP {resp.status_code})")
                return False
            elif resp.status_code in (302, 307):
                # 重定向到登录页表示 cookie 已失效
                logger.warning(f"[{self.account.username}] Cookie 已失效 (重定向到登录页)")
                return False
            else:
                logger.warning(f"[{self.account.username}] 验证请求异常 (HTTP {resp.status_code})")
                return None
        except Exception as e:
            logger.warning(f"[{self.account.username}] 账号验证异常: {e}")
            return None


class AccountPool:
    """
    Twitter 账号池 - 支持轮询和自动故障转移

    冷却策略：
    - 连续失败 3 次 → 冷却 30 分钟
    - 连续失败 5 次 → 冷却 2 小时
    - 连续失败 10 次 → 冷却 24 小时（需手动恢复）

    工作模式：
    - 服务启动时一次性从数据库加载所有账号到内存
    - 运行时所有操作在内存中进行
    - 服务停止时批量更新账号统计信息到数据库
    """

    def __init__(
        self,
        storage: Storage,
        proxy: str | None = None,
        cooldown_after_3_fails: int = 1800,      # 30 分钟
        cooldown_after_5_fails: int = 7200,      # 2 小时
        cooldown_after_10_fails: int = 86400,    # 24 小时
        min_interval: float = 0,                  # 单账号最小请求间隔（秒），0 表示不限速
    ):
        """
        初始化账号池

        Args:
            storage: Storage 实例
            proxy: 代理地址，创建 AccountSession 时使用
            cooldown_after_3_fails: 连续失败 3 次后的冷却秒数
            cooldown_after_5_fails: 连续失败 5 次后的冷却秒数
            cooldown_after_10_fails: 连续失败 10 次后的冷却秒数
            min_interval: 单账号最小请求间隔（秒），0 表示不限速
        """
        self.storage = storage
        self._proxy = proxy
        self._min_interval = min_interval
        self.cooldown_config = {
            3: cooldown_after_3_fails,
            5: cooldown_after_5_fails,
            10: cooldown_after_10_fails,
        }
        self._last_used_username: Optional[str] = None
        self._last_request_time: Dict[str, datetime] = {}  # 单账号限速追踪
        self._consecutive_failures: Dict[str, int] = {}  # 账号连续失败次数
        self._accounts: Dict[str, Account] = {}  # 内存中的账号池
        self._sessions: Dict[str, AccountSession] = {}  # 账号独立 Session 缓存

        # 启动时从数据库加载所有账号
        # self.load_accounts_from_db()

    def load_accounts_from_db(self) -> None:
        """从数据库加载所有账号到内存，并同时创建对应的 AccountSession（带 storage 引用）"""
        accounts_data = self.storage.get_all_accounts()
        for data in accounts_data:
            # 确保 datetime 字段正确转换
            for field in ['last_used_at', 'cooldown_until', 'created_at', 'updated_at']:
                if field in data and isinstance(data[field], datetime):
                    pass  # 已经是 datetime
                elif field in data and data[field]:
                    # 如果是字符串或其他格式，尝试转换
                    try:
                        data[field] = datetime.fromisoformat(str(data[field]))
                    except (ValueError, TypeError):
                        data[field] = None

            # 兼容手动写入 MongoDB 时 enabled 为空字符串的情况
            if "enabled" in data and not isinstance(data["enabled"], bool):
                if isinstance(data["enabled"], str) and data["enabled"].strip():
                    data["enabled"] = data["enabled"].lower() in ("true", "1", "yes")
                else:
                    data["enabled"] = True

            account = Account.model_validate(data)
            self._accounts[account.username] = account
            # 初始化时即创建对应的 Session，传入 storage 引用
            self._sessions[account.username] = AccountSession(account, self._proxy, storage=self.storage)

    def shutdown(self) -> None:
        """服务停止时批量更新账号统计信息到数据库"""
        for account in self._accounts.values():
            self._update_account_in_db(account)

    def _update_account_in_db(self, account: Account) -> None:
        """将单个账号更新到数据库"""
        self.storage.update_account_from_model(account)

    def set_rate_limit_interval(self, interval: float) -> None:
        """动态调整单账号速率限制间隔"""
        self._min_interval = interval

    def get_next_account(self) -> Optional[Account]:
        """
        获取下一个可用账号（轮询模式 + 速率限制，从内存中获取）

        Returns:
            Account 对象，如果没有可用账号则返回 None
        """
        now = datetime.utcnow()
        min_interval = self._min_interval

        # 从内存中获取可用账号（并发安全：GIL 保护 dict 操作）
        available_accounts = [
            acc for acc in self._accounts.values()
            if acc.enabled
            and (acc.cooldown_until is None or acc.cooldown_until < now)
            and (
                acc.username not in self._last_request_time
                or (now - self._last_request_time[acc.username]).total_seconds() >= min_interval
            )
        ]

        if not available_accounts:
            return None

        # 轮询逻辑
        if self._last_used_username is None:
            account = available_accounts[0]
        else:
            # 找到上次使用的账号，返回下一个
            found = False
            for i, acc in enumerate(available_accounts):
                if acc.username == self._last_used_username:
                    next_index = (i + 1) % len(available_accounts)
                    account = available_accounts[next_index]
                    found = True
                    break
            if not found:
                account = available_accounts[0]

        self._last_used_username = account.username
        self._last_request_time[account.username] = now
        return account

    def set_proxy(self, proxy: str | None) -> None:
        """
        设置代理，并重建所有已有账号的 Session

        Args:
            proxy: 代理地址
        """
        self._proxy = proxy
        # 重建所有已有账号的 Session
        for username, account in self._accounts.items():
            self._sessions[username] = AccountSession(account, self._proxy, storage=self.storage)

    def ensure_all_sessions_ready(self, max_workers: int = 20) -> None:
        """
        批量初始化所有账号的 ClientTransaction 签名。
        使用线程池并发获取签名材料，大幅缩短初始化时间。

        Args:
            max_workers: 并发线程数
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        ready_count = 0
        fail_count = 0
        need_init = [
            (username, session) for username, session in self._sessions.items()
            if session.client_transaction is None
        ]

        if not need_init:
            logger.info("所有账号签名材料已就绪")
            return

        logger.info(f"正在批量初始化 {len(need_init)} 个账号的签名材料（并发 {max_workers}）...")

        with ThreadPoolExecutor(max_workers=min(max_workers, len(need_init))) as executor:
            future_map = {
                executor.submit(session.ensure_client_transaction): username
                for username, session in need_init
            }
            for future in as_completed(future_map):
                username = future_map[future]
                try:
                    if future.result():
                        ready_count += 1
                    else:
                        fail_count += 1
                        logger.warning(f"[{username}] 签名材料初始化失败")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"[{username}] 签名材料初始化异常: {e}")

        logger.info(f"签名初始化完成：成功 {ready_count}，失败 {fail_count}")

    def verify_all_accounts(self, max_workers: int = 20) -> Dict[str, int]:
        """
        批量校验所有账号的 cookie 有效性。
        自动将无效账号标记为禁用，并更新 DB。

        Args:
            max_workers: 并发线程数

        Returns:
            {"valid": int, "invalid": int, "unknown": int}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        valid = 0
        invalid = 0
        unknown = 0

        usernames = list(self._sessions.keys())
        if not usernames:
            logger.info("没有账号需要校验")
            return {"valid": 0, "invalid": 0, "unknown": 0}

        logger.info(f"正在批量校验 {len(usernames)} 个账号的 cookie 有效性...")

        def _verify(username: str) -> tuple[str, Optional[bool]]:
            session = self._sessions.get(username)
            if session is None:
                return username, None
            return username, session.verify_account()

        with ThreadPoolExecutor(max_workers=min(max_workers, len(usernames))) as executor:
            future_map = {
                executor.submit(_verify, username): username
                for username in usernames
            }
            for future in as_completed(future_map):
                username = future_map[future]
                try:
                    _, result = future.result()
                    if result is True:
                        valid += 1
                    elif result is False:
                        invalid += 1
                        # 自动禁用账号
                        logger.warning(f"[{username}] Cookie 无效，自动禁用账号")
                        self.mark_enabled(username, False)
                        self.storage.mark_account_enabled(username, False)
                    else:
                        unknown += 1
                except Exception as e:
                    unknown += 1
                    logger.error(f"[{username}] 校验过程异常: {e}")

        logger.info(f"Cookie 校验完成：有效 {valid}，无效 {invalid}，不确定 {unknown}")
        return {"valid": valid, "invalid": invalid, "unknown": unknown}

    def get_next_session_with_sig(self) -> Optional[AccountSession]:
        """
        获取下一个可用账号的独立 Session，并确保其 ClientTransaction 签名已就绪。
        如果签名未初始化，自动尝试获取（包括首次获取和缓存命中）。

        Returns:
            AccountSession 对象，签名就绪；若无可用账号则返回 None
        """
        session = self.get_next_session()
        if session is None:
            return None
        if session.client_transaction is None:
            session.ensure_client_transaction()
        return session

    def get_next_session(self) -> Optional[AccountSession]:
        """
        获取下一个可用账号的独立 Session（轮询模式）
        Session 在 load_accounts_from_db / add_account 时已创建

        Returns:
            AccountSession 对象，如果没有可用账号则返回 None
        """
        account = self.get_next_account()
        if account is None:
            return None
        return self._sessions.get(account.username)

    def remove_session(self, username: str) -> None:
        """
        移除账号的独立 Session（账号被禁用或 cookie 更新时使用）

        Args:
            username: 账号用户名
        """
        if username in self._sessions:
            del self._sessions[username]

    def record_success(self, account: Account) -> None:
        """
        记录成功请求（仅更新内存，不立即写入数据库）

        Args:
            account: 使用的账号
        """
        # 更新内存中的账号统计
        if account.username in self._accounts:
            acc = self._accounts[account.username]
            acc.request_count += 1
            acc.success_count += 1
            acc.last_used_at = datetime.utcnow()
            acc.updated_at = datetime.utcnow()
        # 重置连续失败计数
        if account.username in self._consecutive_failures:
            del self._consecutive_failures[account.username]

    def record_failure(self, account: Account, error: str = "") -> None:
        """
        记录失败请求并计算冷却时间（仅更新内存，不立即写入数据库）

        Args:
            account: 使用的账号
            error: 错误信息
        """
        # 更新连续失败计数
        consecutive_fails = self._consecutive_failures.get(account.username, 0) + 1
        self._consecutive_failures[account.username] = consecutive_fails

        # 计算冷却时间
        cooldown_seconds = self._get_cooldown_seconds(consecutive_fails)
        cooldown_until = datetime.utcnow() + timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None

        # 更新内存中的账号统计
        if account.username in self._accounts:
            acc = self._accounts[account.username]
            acc.request_count += 1
            acc.fail_count += 1
            acc.last_error = error
            acc.last_used_at = datetime.utcnow()
            acc.cooldown_until = cooldown_until
            acc.updated_at = datetime.utcnow()

    def _get_cooldown_seconds(self, consecutive_fails: int) -> int:
        """
        根据连续失败次数获取冷却时间（秒）

        Args:
            consecutive_fails: 连续失败次数

        Returns:
            冷却秒数，0 表示不冷却
        """
        if consecutive_fails >= 10:
            return self.cooldown_config[10]
        elif consecutive_fails >= 5:
            return self.cooldown_config[5]
        elif consecutive_fails >= 3:
            return self.cooldown_config[3]
        else:
            return 0  # 1-2 次失败不冷却

    def mark_enabled(self, username: str, enabled: bool) -> None:
        """
        手动启用/禁用账号

        Args:
            username: 账号用户名
            enabled: 是否启用
        """
        # 更新内存
        if username in self._accounts:
            self._accounts[username].enabled = enabled
        # 更新数据库
        self.storage.mark_account_enabled(username, enabled)
        # 如果启用，重置连续失败计数
        if enabled and username in self._consecutive_failures:
            del self._consecutive_failures[username]

    def get_all_accounts(self) -> List[Account]:
        """获取所有账号（从内存中获取）"""
        return list(self._accounts.values())

    def add_account(self, username: str, cookie: str, enabled: bool = True) -> Account:
        """
        添加新账号

        Args:
            username: 账号用户名
            cookie: cookie 字符串
            enabled: 是否启用

        Returns:
            新添加的 Account 对象
        """
        # 先保存到数据库
        account_data = {
            "username": username,
            "cookie": cookie,
            "enabled": enabled,
            "last_used_at": None,
            "request_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "last_error": None,
            "cooldown_until": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        self.storage.save_account(account_data)
        # 同时添加到内存
        account = Account(**account_data)
        self._accounts[username] = account
        # 同步创建对应的 Session，传入 storage 引用
        self._sessions[username] = AccountSession(account, self._proxy, storage=self.storage)
        return account

    def get_account_stats(self) -> Dict[str, Any]:
        """
        获取账号池统计信息

        Returns:
            统计信息字典
        """
        accounts = self.get_all_accounts()
        total = len(accounts)
        enabled = sum(1 for a in accounts if a.enabled)
        available = sum(1 for a in accounts if a.is_available())
        in_cooldown = total - available

        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "available": available,
            "in_cooldown": in_cooldown,
        }
