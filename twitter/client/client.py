from __future__ import annotations
import logging
from functools import partial
import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, Literal, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
from curl_cffi.requests import Session, Response
from ..errors import TweetNotAvailable
from ..tweet import Tweet, tweet_from_data
from ..errors import (
    AccountLocked,
    AccountSuspended,
    BadRequest,
    Forbidden,
    NotFound,
    RequestTimeout,
    ServerError,
    TooManyRequests,
    TwitterException,
    Unauthorized,
)
from .constants import TOKEN, DOMAIN, JSCODE, APPEND_EXPORT_VALUES
from ..ui_metrics import solve_ui_metrics
from ..user import User
from ..utils import (
    Flow,
    Result,
    build_tweet_data,
    build_user_data,
    find_dict,
    cookie_str_to_dict,
    cookie_dict_to_str
)
from .gql import GQLClient
from bs4 import BeautifulSoup
from ..account_pool import AccountPool
from .rpc_client import RpcHTTPClient

class Client:
    """
    A client for interacting with the Twitter API.
    Since this class is for asynchronous use,
    methods must be executed using await.

    Parameters
    ----------
    language : :class:`str` | None, default=None
        The language code to use in API requests.
    proxy : :class:`str` | None, default=None
        The proxy server URL to use for request
        (e.g., 'http://0.0.0.0:0000').
    captcha_solver : :class:`.Capsolver` | None, default=None
        See :class:`.Capsolver`.

    Examples
    --------
    >>> client = Client(language='en-US')

    >>> client.login(
    ...     auth_info_1='example_user',
    ...     auth_info_2='email@example.com',
    ...     password='00000000'
    ... )
    """

    def __init__(
        self,
        language: str | None = 'zh-cn',
        proxy: str | None = None,
        account_pool: Optional[AccountPool] = None,
        rpc_model: bool = False,
        rpc_url: str = None,
        rpc_timeout: float = None,
        storage: Optional[Any] = None,
    ) -> None:
        # 如果传入了代理 URL，则使用它；否则尝试从环境变量获取
        self.rpc_model = rpc_model
        # 原始响应持久化 + 签名缓存（可选）
        self.storage = storage
        if rpc_model:
            from .rpc_client import DEFAULT_TIMEOUT
            self.rpc_client = RpcHTTPClient(
                base_url=rpc_url,
                timeout=rpc_timeout if rpc_timeout else DEFAULT_TIMEOUT,
            )
        else:
            if not proxy:
                from dotenv import load_dotenv
                load_dotenv()
                proxy = os.getenv("PROXY")
            self.language = language or 'zh-cn'
            self.proxy = proxy
            self.account_pool = account_pool
            self._token = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
            self._user_id = None
            self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Norton/131.0.0.0"
            self._act_as = None
            self.is_login = False

            self.http = Session(
                proxy=proxy,
                impersonate="chrome131"
            )
            self.gql = GQLClient(self)
            self.cookies_dict = {}
            self.cookies = ""

            self.endpoint_params = {}  # 延迟初始化（在 init_client 中填充）

            # 如果配置了账号池，将代理设置传入账号池
            if self.account_pool:
                self.account_pool.set_proxy(self.proxy)

    def init_client(self):
        """
        初始化客户端：获取 GraphQL 端点参数。
        签名材料已由 AccountSession 按需获取，此处不再通过 Playwright 获取。
        """
        # 1. 尝试从缓存加载端点参数
        if self.storage:
            cached_params = self.storage.get_endpoint_params()
            if cached_params:
                self.endpoint_params = cached_params
                logger.info("端点参数从缓存恢复")
                # 用硬编码值补充缓存中可能缺失的端点（如懒加载 chunk 中的 BirdwatchFetchGlobalTimeline）
                base_url = 'https://x.com/i/api/graphql'
                added = 0
                for key, value in APPEND_EXPORT_VALUES.items():
                    if key not in self.endpoint_params:
                        ep = {'params': {}, 'endpoint': f'{base_url}/{value["queryId"]}/{key}'}
                        metadata = value.get('metadata', {})
                        featureSwitches = metadata.get("featureSwitches", [])
                        fieldToggle = metadata.get("fieldToggles", [])
                        if featureSwitches:
                            ep['params']['features'] = {f: True for f in featureSwitches}
                        if fieldToggle:
                            ep['params']['fieldToggles'] = {f: True for f in fieldToggle}
                        self.endpoint_params[key] = ep
                        added += 1
                if added:
                    logger.info(f"硬编码补充了 {added} 个缺失端点到缓存中")
                    # 更新缓存，避免下次启动重复补充
                    self.storage.save_endpoint_params(self.endpoint_params)
                return

        # 2. 缓存未命中，从 x.com 获取 JS bundles 提取
        logger.info("正在从 x.com 获取 JS bundles 提取端点参数...")
        headers = {
            'User-Agent': self._user_agent,
            'Referer': 'https://x.com/',
            'Accept': '*/*',
        }
        resp = self.http.get('https://x.com/', headers=headers, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 查找 JS bundle URL（x.com 曾用 main.js/shared.js，现改用 entry-client 单 bundle）
        js_urls = []
        for script in soup.select('script[src]'):
            src = script.get('src', '')
            if src.endswith('.js'):
                # 匹配 main.js / shared~bundle / entry-client 等格式
                if any(kw in src for kw in ('/main.', 'shared~bundle', 'entry-client')):
                    js_urls.append(src)

        # fallback: 从 link preload 查找
        if not js_urls:
            for link in soup.select('link[as="script"]'):
                href = link.get('href', '')
                if href.endswith('.js'):
                    js_urls.append(href)

        def _resolve_url(url):
            if url.startswith('//'):
                return 'https:' + url
            elif url.startswith('/'):
                return 'https://x.com' + url
            return url

        # 下载 JS bundles 并用 exejs 提取
        export_values = {}
        if js_urls:
            import exejs
            for js_url in js_urls:
                full_url = _resolve_url(js_url)
                logger.info(f"尝试从 {full_url.split('/')[-1][:60]} 提取端点参数...")
                try:
                    js_resp = self.http.get(full_url, headers=headers, timeout=30)
                    js_content = js_resp.text
                    exports = exejs.compile(JSCODE % js_content).call("getExportValues")
                    if exports:
                        export_values.update(exports)
                        logger.info(f"从 {js_url.split('/')[-1][:40]} 提取到 {len(exports)} 个端点")
                except Exception as e:
                    logger.warning(f"{js_url.split('/')[-1][:40]} 提取失败: {e}")

        # 用硬编码端点参数兜底：若 JS 提取为空则完全替换，否则补充缺失的端点
        if not export_values:
            logger.warning("JS 下载或 exejs 提取失败，使用硬编码备选端点参数")
            export_values = APPEND_EXPORT_VALUES
        else:
            # 硬编码值补充提取缺失的端点（优先保留 JS 提取的值）
            for key, value in APPEND_EXPORT_VALUES.items():
                if key not in export_values:
                    export_values[key] = value

        # 构建 endpoint_params
        base_url = 'https://x.com/i/api/graphql'
        endpoint_params = {}
        for key, value in export_values.items():
            endpoint_params[key] = {}
            metadata = value['metadata']
            featureSwitches = metadata.get("featureSwitches", [])
            fieldToggle = metadata.get("fieldToggles", [])
            endpoint_params[key]["params"] = {}
            if featureSwitches:
                endpoint_params[key]["params"]['features'] = {feature: True for feature in featureSwitches}
            if fieldToggle:
                endpoint_params[key]["params"]['fieldToggles'] = {field: True for field in fieldToggle}
            endpoint_params[key]['endpoint'] = base_url + '/' + value['queryId'] + '/' + key

        self.endpoint_params = endpoint_params

        # 缓存到 MongoDB
        if self.storage:
            self.storage.save_endpoint_params(endpoint_params)
            logger.info("端点参数已缓存到 MongoDB")
        
    
    def request(
        self,
        method: str,
        url: str,
        auto_unlock: bool = True,
        raise_exception: bool = True,
        **kwargs
    ) -> tuple[dict | Any, Response]:
        ':meta private:'

        # 如果配置了账号池，获取下一个可用账号的独立 Session
        acct_session = None
        headers = kwargs.pop('headers', {})
        if self.account_pool:
            # 重试等待可用账号（最多等 30 秒，避开单账号 0.5s 冷却期）
            # 应对 max_workers(100) >> 账号数(10) 的并发场景：
            # 37个任务抢10个账号，每0.5s冷却释放一轮，约 4 轮(2s)全部消化
            # 若请求本身耗时较长，额外预留缓冲时间
            max_wait = 30.0
            poll_interval = 0.3
            waited = 0.0
            while waited < max_wait:
                acct_session = self.account_pool.get_next_session_with_sig()
                if acct_session is not None:
                    break
                time.sleep(poll_interval)
                waited += poll_interval
            if acct_session is None:
                raise TwitterException(
                    f"No available accounts in the account pool "
                    f"(waited {max_wait:.0f}s, "
                    f"accounts={len(self.account_pool.get_all_accounts())}, "
                    f"enabled={sum(1 for a in self.account_pool.get_all_accounts() if a.enabled)})"
                )
        

        # 使用账号 Session 生成签名
        if acct_session:
            tid = acct_session.generate_transaction_id(method=method, path=urlparse(url).path)
        else:
            tid = ''
        headers['X-Client-Transaction-Id'] = tid

        # 使用账号独立 Session 或默认 Session 发送请求
        if acct_session:
            response = acct_session.http.request(method, url, headers=headers, cookies=acct_session.cookies_dict, **kwargs)
        else:
            response = self.http.request(method, url, headers=headers, cookies=self.cookies_dict, **kwargs)

        try:
            response_data = response.json()
        except json.decoder.JSONDecodeError:
            response_data = response.text

        if isinstance(response_data, dict) and 'errors' in response_data:
            error_code = response_data['errors'][0].get('code')
            error_message = response_data['errors'][0].get('message')

            # 如果没有 code 字段（Twitter 有时返回不规范格式），统一当作 TweetNotAvailable
            if error_code is None:
                raise TweetNotAvailable(error_message)

            # 记录失败
            if acct_session and self.account_pool:
                self.account_pool.record_failure(acct_session.account, error_message)

            if error_code in (37, 64):
                # Account suspended
                raise AccountSuspended(error_message)

            if error_code == 326:
                # Account unlocking
                raise AccountLocked(
                    'Your account is locked. Visit '
                    f'https://{DOMAIN}/account/access to unlock it.'
                )

        status_code = response.status_code

        if status_code >= 400 and raise_exception:
            # 记录失败
            if acct_session and self.account_pool:
                self.account_pool.record_failure(acct_session.account, f"HTTP {status_code}")

            message = f'status: {status_code}, message: "{response.text}"'
            if status_code == 400:
                raise BadRequest(message, headers=response.headers)
            elif status_code == 401:
                raise Unauthorized(message, headers=response.headers)
            elif status_code == 403:
                raise Forbidden(message, headers=response.headers)
            elif status_code == 404:
                raise NotFound(message, headers=response.headers)
            elif status_code == 408:
                raise RequestTimeout(message, headers=response.headers)
            elif status_code == 429:
                # 强制冷却 60 秒，避免立即重试再次触发限流
                if acct_session and self.account_pool:
                    acct_session.account.cooldown_until = datetime.utcnow() + timedelta(seconds=60)
                raise TooManyRequests(message, headers=response.headers)
            elif 500 <= status_code < 600:
                raise ServerError(message, headers=response.headers)
            else:
                raise TwitterException(message, headers=response.headers)

        # 记录成功
        if acct_session and self.account_pool:
            self.account_pool.record_success(acct_session.account)

        if status_code == 200:
            return response_data, response

        return response_data, response

    def get(self, url, **kwargs) -> tuple[dict | Any, Response]:
        ':meta private:'
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs) -> tuple[dict | Any, Response]:
        ':meta private:'
        return self.request('POST', url, **kwargs)

    def _remove_duplicate_ct0_cookie(self) -> None:
        cookies = {}
        for cookie in self.http.cookies.jar:
            if 'ct0' in cookies and cookie.name == 'ct0':
                continue
            cookies[cookie.name] = cookie.value
        self.http.cookies = list(cookies.items())


    def _get_csrf_token(self) -> str:
        """
        Retrieves the Cross-Site Request Forgery (CSRF) token from the
        current session's cookies.

        Returns
        -------
        :class:`str`
            The CSRF token as a string.
        """
        return self.cookies_dict.get('ct0')

    @property
    def _base_headers(self) -> dict[str, str]:
        """
        Base headers for Twitter API requests.
        Note: Cookie 不在 headers 中传递，而是通过 Session 的 cookies 参数管理，
        以支持多账号独立 Session 模式。
        """
        headers = {
            'authorization': f'Bearer {self._token}',
            'content-type': 'application/json',
            'X-Twitter-Auth-Type': 'OAuth2Session',
            'X-Twitter-Active-User': 'yes',
            'Referer': f'https://{DOMAIN}/',
            'User-Agent': self._user_agent,
        }
        if self.language is not None:
            headers['Accept-Language'] = self.language
            headers['X-Twitter-Client-Language'] = self.language
        if self._act_as is not None:
            headers['X-Act-As-User-Id'] = self._act_as
        return headers

    def _get_guest_token(self) -> str:
        # response, _ = self.v11.guest_activate()
        # guest_token = response['guest_token']
        # return guest_token
        return self.cookies_dict.get("gt")



    def set_cookies(self, cookies: Union[Dict, str], clear_cookies: bool = False) -> None:
        """
        Sets cookies.
        You can skip the login procedure by loading a saved cookies.

        Parameters
        ----------
        cookies : :class:`dict`
            The cookies to be set as key value pair.

        Examples
        --------
        >>> with open('cookies.json', 'r', encoding='utf-8') as f:
        ...     client.set_cookies(json.load(f))

        See Also
        --------
        .get_cookies
        .load_cookies
        .save_cookies
        """
        
        if not cookies:
            raise ValueError('cookies is null')
        
        if isinstance(cookies, str):
            self.cookies = cookies
            self.cookies_dict = cookie_str_to_dict(cookies)
        else:
            self.cookies_dict = cookies
            self.cookies = cookie_dict_to_str(cookies)
        

    
    def get_tweet_by_id(
        self, tweet_id: str, cursor: str | None = None
    ) -> Tweet:
        """
        Fetches a tweet by tweet ID.

        Parameters
        ----------
        tweet_id : :class:`str`
            The ID of the tweet.

        Returns
        -------
        :class:`Tweet`
            A Tweet object representing the fetched tweet.
        """
        if self.rpc_model:
            response = self.rpc_client.invoke("twitter", "TweetDetail", params={"tweet_id": tweet_id, "cursor": cursor})
        else:
            response, _ = self.gql.tweet_detail(tweet_id, cursor)

        self._save_raw_response(
            "TweetDetail",
            response,
            params={"tweet_id": tweet_id, "cursor": cursor},
            post_id=tweet_id,
        )

        if 'errors' in response:
            raise TweetNotAvailable(response['errors'][0]['message'])

        entries = find_dict(response, 'entries', find_one=True)[0]
        reply_to = []
        replies_list = []
        related_tweets = []
        tweet = None

        for entry in entries:
            if entry['entryId'].startswith('cursor'):
                continue
            tweet_object = tweet_from_data(self, entry)
            if tweet_object is None:
                continue

            if entry['entryId'].startswith('tweetdetailrelatedtweets'):
                related_tweets.append(tweet_object)
                continue

            if entry['entryId'] == f'tweet-{tweet_id}':
                tweet = tweet_object
                break
            # else:
            #     if tweet is None:
            #         reply_to.append(tweet_object)
            #     else:
            #         replies = []
            #         sr_cursor = None
            #         show_replies = None

            #         for reply in entry['content']['items'][1:]:
            #             if 'tweetcomposer' in reply['entryId']:
            #                 continue
            #             if 'tweet' in reply.get('entryId'):
            #                 rpl = tweet_from_data(self, reply)
            #                 if rpl is None:
            #                     continue
            #                 replies.append(rpl)
            #             if 'cursor' in reply.get('entryId'):
            #                 sr_cursor = reply['item']['itemContent']['value']
            #                 show_replies = partial(
            #                     self._show_more_replies,
            #                     tweet_id,
            #                     sr_cursor
            #                 )
            #         tweet_object.replies = Result(
            #             replies,
            #             show_replies,
            #             sr_cursor
            #         )
            #         replies_list.append(tweet_object)

            #         display_type = find_dict(entry, 'tweetDisplayType', True)
            #         if display_type and display_type[0] == 'SelfThread':
            #             tweet.thread = [tweet_object, *replies]

        # if entries[-1]['entryId'].startswith('cursor'):
        #     # if has more replies
        #     reply_next_cursor = entries[-1]['content']['itemContent']['value']
        #     _fetch_more_replies = partial(self._get_more_replies,
        #                                   tweet_id, reply_next_cursor)
        # else:
        #     reply_next_cursor = None
        #     _fetch_more_replies = None

        # tweet.replies = Result(
        #     replies_list,
        #     _fetch_more_replies,
        #     reply_next_cursor
        # )
        # tweet.reply_to = reply_to
        # tweet.related_tweets = related_tweets

        return tweet

    def parse_communitynotes_entry(self, response: dict) -> list[Tweet]:
        tweets = []
        entries_result = find_dict(response, 'entries', find_one=True)
        if not entries_result:
            return
        entries = entries_result[0]

        for entry in entries:
            # 跳过 cursor 条目
            if entry['entryId'].startswith('cursor'):
                continue

            # 跳过 header 条目
            if entry['entryId'].startswith('header'):
                continue

            # __typename 在 content 对象内
            content = entry.get('content', {})
            typename = content.get('__typename')

            # 处理 TimelineTimelineModule 类型（包含 items 数组）
            if typename == 'TimelineTimelineModule':
                items = content.get('items', [])
                for item in items:
                    # item 结构：{ "item": { "itemContent": { "tweet_results": {...} } } }
                    item_data = item.get('item', {})
                    item_content = item_data.get('itemContent', {})
                    tweet_results = item_content.get('tweet_results')
                    if tweet_results:
                        tweet_object = tweet_from_data(self, tweet_results)
                        if tweet_object:
                            tweets.append(tweet_object)
            # 处理 TimelineTimelineItem 类型
            elif typename == 'TimelineTimelineItem':
                item_content = content.get('itemContent', {})
                tweet_results = item_content.get('tweet_results')
                if tweet_results:
                    tweet_object = tweet_from_data(self, tweet_results)
                    if tweet_object:
                        tweets.append(tweet_object)
        return tweets
        

    def communitynotes_new(self, timelineId: str) -> list[Tweet]:
        """
        获取最新的 Community Notes 推文列表。

        Returns
        -------
        :class:`list`[:class:`Tweet`]
            包含最新 Community Notes 推文列表。
        """
        if self.rpc_model:
            response = self.rpc_client.invoke("twitter", "GenericTimeline", params={"timelineId": timelineId})
        else:
            response, _ = self.gql.generic_timeline(timelineId)

        self._save_raw_response(
            "GenericTimeline",
            response,
            params={"timelineId": timelineId},
        )

        if 'errors' in response:
            return
            # raise TweetNotAvailable(response['errors'][0]['message'])

        return self.parse_communitynotes_entry(response)

    def communitynotes_rated_helpful(self) -> dict:
        """
        获取已标记为有帮助的 Community Notes 推文列表。

        Returns
        -------
        dict
            包含 'rated_helpful' (Tweet列表), 'new' (Tweet列表),
            'helpful_notes' (原始 API 响应), 'new_notes' (原始 API 响应)
        """
        if self.rpc_model:
            response = self.rpc_client.invoke("twitter", "BirdwatchFetchGlobalTimeline", params={})
        else:
            response, _ = self.gql.birdwatch_fetch_global_timeline()

        self._save_raw_response("BirdwatchFetchGlobalTimeline", response)

        if not response:
            logger.warning("BirdwatchFetchGlobalTimeline 返回空（端点不可用），跳过本次采集")
            return {'rated_helpful': [], 'new': [], 'helpful_notes': {}, 'new_notes': {}}

        if 'errors' in response:
            err_msg = response['errors'][0].get('message', str(response['errors']))
            logger.error(f"BirdwatchFetchGlobalTimeline API error: {err_msg}")
            raise TweetNotAvailable(err_msg)

        result = {}
        result['rated_helpful'] = self.parse_communitynotes_entry(response) or []

        # 安全获取 timelineId，处理 viewer 缺失的情况
        try:
            viewer = response.get('data', {}).get('viewer')
            if viewer is None:
                logger.error(
                    "No 'viewer' in BirdwatchFetchGlobalTimeline response — "
                    "user may not be authenticated or cookies expired. "
                    f"Response keys: {list(response.get('data', {}).keys())}"
                )
                result['new'] = []
                return result

            timelines = viewer.get('birdwatch_home_page', {}).get('body', {}).get('timelines', [])
            if len(timelines) < 2:
                logger.error(
                    f"Expected at least 2 timelines, got {len(timelines)}. "
                    f"viewer keys: {list(viewer.keys())}"
                )
                result['new'] = []
                return result

            timelineId = timelines[1]['timeline']['id']
        except (KeyError, IndexError, TypeError) as e:
            logger.error(
                f"Failed to extract timelineId from response: {type(e).__name__}: {e}",
                exc_info=True,
            )
            result['new'] = []
            return result

        new_tweets = self.communitynotes_new(timelineId)
        result['new'] = new_tweets or []
        return result
    
    def communitynotes_detail(self, tweet_id: str, tweet_data: dict | None = None) -> dict:
        """
        获取 Community Notes 推文详情。

        Parameters
        ----------
        tweet_id : str
            推文 ID
        tweet_data : dict | None
            可选的 tweet result 原始数据（由 Tweet._data 传入）。
            提供此参数时直接从已有数据中提取，无需调用 BirdwatchFetchNotes API。

        Returns
        -------
        dict
            包含 posts, notes, contributors 的解析结果
        """
        from ..parser import parse_note_data
        
        # 如果传入了 tweet_data，直接从已有数据中提取 notes
        if tweet_data is not None:
            api_response = {
                "data": {
                    "tweet_result_by_rest_id": {
                        "result": tweet_data
                    }
                }
            }
            return parse_note_data(api_response)
        
        if self.rpc_model:
            response = self.rpc_client.invoke("twitter", "BirdwatchFetchNotes", params={"tweet_id": tweet_id})
        else:
            response, _ = self.gql.birdwatch_fetch_notes(tweet_id)

        if 'errors' in response:
            raise TweetNotAvailable(response['errors'][0]['message'])
        self._save_raw_response("BirdwatchFetchNotes", response)
        return parse_note_data(response)

    def _save_raw_response(
        self,
        endpoint: str,
        response: Any,
        params: Optional[Dict[str, Any]] = None,
        post_id: Optional[str] = None,
    ) -> None:
        """
        将接口原始响应通过 storage 持久化。失败不影响主流程。
        """
        if self.storage is None:
            return
        try:
            self.storage.save_api_response(
                endpoint=endpoint,
                response=response,
                params=params,
                post_id=post_id,
            )
        except Exception as e:
            logger.warning(f"Failed to persist raw response for {endpoint}: {e}")
        