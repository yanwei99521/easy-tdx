"""Dependency injection for Web API routers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Request

from easy_tdx.client import AsyncTdxClient


@lru_cache(maxsize=1)
def get_ths_web_client() -> Any:
    """返回共享的同花顺公开网页客户端（仅行情快照短时缓存）。"""
    from easy_tdx.ths_web import ThsWebClient

    return ThsWebClient()


def get_client(request: Request) -> AsyncTdxClient:
    """从 app.state 获取共享的 AsyncTdxClient 实例。"""
    client: AsyncTdxClient = request.app.state.tdx_client
    return client


def get_mac_client(request: Request) -> Any:
    """从 app.state 获取共享的 AsyncMacClient 实例。"""
    from easy_tdx.exceptions import TdxConnectionError

    client: Any | None = request.app.state.mac_client
    if client is None:
        raise TdxConnectionError("MAC 客户端未连接")
    return client


def get_mac_client_optional(request: Request) -> Any | None:
    """从 app.state 获取 AsyncMacClient 实例，未连接时返回 None（不抛异常）。

    供需要"MAC 不可用时自动回退标准 TdxClient"的端点使用（如 ``/bars``）。
    其他强制依赖 MAC 的端点（``/mac/*``）仍用 :func:`get_mac_client`。
    """
    return request.app.state.mac_client


def get_ex_client(request: Request) -> Any:
    """从 app.state 获取共享的 AsyncExTdxClient 实例（可选）。"""
    client: Any | None = request.app.state.ex_client
    if client is None:
        from easy_tdx.exceptions import TdxConnectionError

        raise TdxConnectionError("扩展市场客户端未启用")
    return client
