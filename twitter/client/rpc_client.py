"""
Rpc HTTP API Client

基于 httpx 和 tenacity 的 Rpc 公开 HTTP API 客户端。
支持同步/异步调用、自动重试、错误处理。

覆盖端点:
  - GET  /health
  - GET  /business/groupList
  - GET  /business/clientQueue
  - POST /business/invoke
  - POST /business/execjs
  - POST /business/cookie
  - POST /business/html
  - POST /v1/chat/completions
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:5612"
DEFAULT_TIMEOUT = 60.0


class RpcError(Exception):
    """Rpc 客户端基础异常"""
    pass


class RpcAPIError(RpcError):
    """Rpc API 返回的业务错误（HTTP 200 但 status != 0）"""

    def __init__(
        self,
        message: str,
        status: int = -1,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.status = status
        self.raw_response = raw_response


class RpcHTTPError(RpcError):
    """HTTP 层错误（网络、超时、4xx/5xx 等）"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试（仅网络错误、超时、断连、5xx）"""
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.RemoteProtocolError):
        # Server disconnected without sending a response — RPC Server 过载，可重试
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _make_retry(attempts: int):
    """构造 tenacity 重试装饰器"""
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


class RpcHTTPClient:
    """
    Rpc 公开 HTTP API 同步客户端

    Usage:
        >>> client = RpcHTTPClient(base_url="http://localhost:5612", api_token="your_token")
        >>> print(client.group_list())
        >>> result = client.invoke(group="test", action="hello", params={"name": "world"})
        >>> client.close()
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_attempts: int = 3,
    ):
        self.base_url = base_url
        self.api_token = api_token
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._client = httpx.Client(
            timeout=timeout,
            headers=self._default_headers(),
        )

    def _default_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    @_make_retry(3)
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        override_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """底层请求方法，自动处理 JSON 序列化与统一响应格式"""
        # if not self.api_token:
        #     raise RpcError("api_token is required")

        url = f"{self.base_url}{path}"

        if params is not None:
            params = {k: v for k, v in params.items() if v is not None}
        if json_data is not None:
            json_data = {k: v for k, v in json_data.items() if v is not None}

        try:
            response = self._client.request(
                method,
                url,
                params=params,
                json=json_data,
                timeout=override_timeout or self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RpcHTTPError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as e:
            raise RpcHTTPError(f"Request failed: {e}") from e

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise RpcHTTPError(f"Invalid JSON response: {e}") from e

        # 统一响应格式处理（OpenAI 端点除外）
        if isinstance(data, dict) and "status" in data:
            if data["status"] != 0:
                raise RpcAPIError(
                    data.get("message", "Unknown error"),
                    status=data["status"],
                    raw_response=data,
                )
        return data

    # ----------------- 生命周期 -----------------

    def close(self) -> None:
        """关闭客户端连接池"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ----------------- 公开 API -----------------

    def health(self) -> Dict[str, Any]:
        """GET /health — 健康检查"""
        return self._request("GET", "/health")

    def group_list(self) -> List[str]:
        """GET /business/groupList — 获取分组列表"""
        resp = self._request("GET", "/business/groupList")
        return resp.get("data", [])

    def client_queue(
        self,
        group: str,
    ) -> List[str]:
        """GET /business/clientQueue — 获取某分组下的客户端队列"""
        if not group:
            raise ValueError("group is required")
        params: Dict[str, Any] = {"group": group}
        resp = self._request("GET", "/business/clientQueue", params=params)
        return resp.get("data", [])

    def invoke(
        self,
        group: str,
        action: str,
        *,
        client_id: Optional[str] = None,
        params: Optional[Union[Dict[str, Any], List[Any]]] = None,
        timeout: Optional[int] = None,
        constant_invoke: Optional[str] = None,
        http_timeout: Optional[float] = None,
    ) -> Any:
        """
        POST /business/invoke — RPC 调用

        :param group: 分组名称（必填）
        :param action: 动作名称（必填）
        :param client_id: 指定客户端 ID，为空则使用轮询/一致性哈希
        :param params: 调用参数，需为 JSON 可序列化对象
        :param timeout: Sekiro 业务超时（秒，传给 RPC Server）
        :param constant_invoke: 一致性哈希开关（如传 "true" 则启用）
        :param http_timeout: HTTP 层超时（秒，覆盖 client 默认超时）
        """
        if not group or not action:
            raise ValueError("group and action are required")

        payload = {
            "group": group,
            "action": action,
            "clientId": client_id,
            "params": params,
            "timeout": timeout,
            "constantInvoke": constant_invoke,
        }
        resp = self._request("POST", "/business/invoke", json_data=payload, override_timeout=http_timeout)
        return resp

    def execjs(
        self,
        group: str,
        code: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        """POST /business/execjs — 在目标客户端执行 JS 代码"""
        if not group or not code:
            raise ValueError("group and code are required")

        payload = {
            "group": group,
            "code": code,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = self._request("POST", "/business/execjs", json_data=payload)
        return resp.get("data")

    def get_cookie(
        self,
        group: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        """POST /business/cookie — 获取目标客户端 Cookie"""
        if not group:
            raise ValueError("group is required")

        payload = {
            "group": group,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = self._request("POST", "/business/cookie", json_data=payload)
        return resp.get("data")

    def get_html(
        self,
        group: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        """POST /business/html — 获取目标客户端 HTML"""
        if not group:
            raise ValueError("group is required")

        payload = {
            "group": group,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = self._request("POST", "/business/html", json_data=payload)
        return resp.get("data")

    def chat_completions(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        group: Optional[str] = None,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        POST /v1/chat/completions — OpenAI 兼容接口（非流式）

        :param model: 模型名称（必填）
        :param messages: 消息列表，如 [{"role": "user", "content": "hello"}]
        :param stream: 是否流式返回（当前仅支持 False）
        :param group: 分组名称
        :param client_id: 指定客户端 ID
        :param constant_invoke: 一致性哈希参数
        :param extra_body: 额外请求参数，将合并到请求体
        """
        if not model:
            raise ValueError("model is required")
        if stream:
            raise NotImplementedError("stream=True is not supported yet")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if group is not None:
            payload["group"] = group
        if client_id is not None:
            payload["clientId"] = client_id
        if constant_invoke is not None:
            payload["constantInvoke"] = constant_invoke

        if extra_body:
            payload.update(extra_body)

        # chat completions 响应格式与标准 API 不同，直接透传 JSON
        url = f"{self.base_url}/v1/chat/completions"
        try:
            response = self._client.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RpcHTTPError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as e:
            raise RpcHTTPError(f"Request failed: {e}") from e

        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise RpcHTTPError(f"Invalid JSON response: {e}") from e


class AsyncRpcHTTPClient:
    """
    Rpc 公开 HTTP API 异步客户端

    Usage:
        >>> async with AsyncRpcHTTPClient(api_token="your_token") as client:
        ...     groups = await client.group_list()
        ...     result = await client.invoke("test", "hello", params={"name": "world"})
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_attempts: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=self._default_headers(),
        )

    def _default_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    @_make_retry(3)
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        override_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.api_token:
            raise RpcError("api_token is required")

        url = f"{self.base_url}{path}"

        if params is not None:
            params = {k: v for k, v in params.items() if v is not None}
        if json_data is not None:
            json_data = {k: v for k, v in json_data.items() if v is not None}

        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json_data,
                timeout=override_timeout or self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RpcHTTPError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as e:
            raise RpcHTTPError(f"Request failed: {e}") from e

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise RpcHTTPError(f"Invalid JSON response: {e}") from e

        if isinstance(data, dict) and "status" in data:
            if data["status"] != 0:
                raise RpcAPIError(
                    data.get("message", "Unknown error"),
                    status=data["status"],
                    raw_response=data,
                )
        return data

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ----------------- 公开 API -----------------

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def group_list(self) -> List[str]:
        resp = await self._request("GET", "/business/groupList")
        return resp.get("data", [])

    async def client_queue(
        self,
        group: str,
    ) -> List[str]:
        if not group:
            raise ValueError("group is required")
        params: Dict[str, Any] = {"group": group}
        resp = await self._request("GET", "/business/clientQueue", params=params)
        return resp.get("data", [])

    async def invoke(
        self,
        group: str,
        action: str,
        *,
        client_id: Optional[str] = None,
        params: Optional[Union[Dict[str, Any], List[Any]]] = None,
        timeout: Optional[int] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        if not group or not action:
            raise ValueError("group and action are required")
        payload = {
            "group": group,
            "action": action,
            "clientId": client_id,
            "params": params,
            "timeout": timeout,
            "constantInvoke": constant_invoke,
        }
        resp = await self._request("POST", "/business/invoke", json_data=payload)
        return resp.get("data")

    async def execjs(
        self,
        group: str,
        code: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        if not group or not code:
            raise ValueError("group and code are required")
        payload = {
            "group": group,
            "code": code,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = await self._request("POST", "/business/execjs", json_data=payload)
        return resp.get("data")

    async def get_cookie(
        self,
        group: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        if not group:
            raise ValueError("group is required")
        payload = {
            "group": group,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = await self._request("POST", "/business/cookie", json_data=payload)
        return resp.get("data")

    async def get_html(
        self,
        group: str,
        *,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
    ) -> Any:
        if not group:
            raise ValueError("group is required")
        payload = {
            "group": group,
            "clientId": client_id,
            "constantInvoke": constant_invoke,
        }
        resp = await self._request("POST", "/business/html", json_data=payload)
        return resp.get("data")

    async def chat_completions(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
        group: Optional[str] = None,
        client_id: Optional[str] = None,
        constant_invoke: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not model:
            raise ValueError("model is required")
        if stream:
            raise NotImplementedError("stream=True is not supported yet")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if group is not None:
            payload["group"] = group
        if client_id is not None:
            payload["clientId"] = client_id
        if constant_invoke is not None:
            payload["constantInvoke"] = constant_invoke

        if extra_body:
            payload.update(extra_body)

        url = f"{self.base_url}/v1/chat/completions"
        try:
            response = await self._client.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RpcHTTPError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as e:
            raise RpcHTTPError(f"Request failed: {e}") from e

        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise RpcHTTPError(f"Invalid JSON response: {e}") from e
