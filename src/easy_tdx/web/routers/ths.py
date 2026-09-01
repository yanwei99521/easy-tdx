"""同花顺公开网页关联板块路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from easy_tdx.ths_web import ThsWebError
from easy_tdx.web.deps import get_ths_web_client
from easy_tdx.web.schemas import DictResponse

router = APIRouter(tags=["ths-web"])


@router.get("/ths/stock/associations", response_model=DictResponse)
async def stock_associations(
    code: str = Query(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$", description="6位股票代码"
    ),
    concept_limit: int = Query(10, ge=1, le=30, description="返回概念板块数量，默认 10"),
    client: Any = Depends(get_ths_web_client),
) -> DictResponse:
    """获取同花顺公开网页中的行业层级、概念板块及板块涨跌幅。

    数据从同花顺公开网页解析，并非官方开放 API。行业归属每次请求重新读取；
    行业/概念行情只在当日内短时缓存，页面没有公开报价的层级会返回 ``null``。
    """
    try:
        return DictResponse.from_dict(await client.get_stock_associations(code, concept_limit))
    except ThsWebError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
