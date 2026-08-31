"""指定股票所属行业及行业当日涨跌幅路由。"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_value_from_str
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["stock-industry"])

# ``get_belong_board`` 的 board_type 来自行情服务器的所属板块响应，
# 与 BoardType（用于板块列表/排行请求）的编码并非始终相同。
# 0/1 是标准协议中的行业一级/二级，部分 MAC 服务器将行业归属返回为 12。
_INDUSTRY_BOARD_TYPES = frozenset({0, 1, 12})


def _finite_float(value: object) -> float | None:
    """Convert a value to a finite float, treating missing values as None."""
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _industry_rows(df: Any, market: str, code: str) -> list[dict[str, Any]]:
    """Filter belonging-board rows to industries and calculate today's change."""
    if df is None or getattr(df, "empty", True):
        return []

    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        try:
            board_type = int(row.get("board_type", -1))
        except (TypeError, ValueError):
            continue
        if board_type not in _INDUSTRY_BOARD_TYPES:
            continue

        close = _finite_float(row.get("close"))
        pre_close = _finite_float(row.get("pre_close"))
        change_pct = (
            round((close - pre_close) / pre_close * 100, 2)
            if close is not None and pre_close not in (None, 0)
            else None
        )
        rows.append(
            {
                "market": market,
                "code": code,
                "industry_code": str(row.get("board_code", "")),
                "industry_name": str(row.get("board_name", "")),
                "board_type": board_type,
                "close": close,
                "pre_close": pre_close,
                "change_pct": change_pct,
            }
        )
    return rows


@router.get("/stock/industry", response_model=DataFrameResponse)
async def stock_industry(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取指定股票所属行业及行业今日涨跌幅。

    行业归属和行业指数的收盘/昨收均从 MAC 行情服务器实时读取，不使用本地缓存，
    因此不会跨交易日复用过期的行业关系或行情数据。
    """
    market_code = market.upper()
    df = await client.get_belong_board(market=market_value_from_str(market_code), code=code)
    rows = _industry_rows(df, market_code, code)
    return DataFrameResponse(data=rows, count=len(rows))
