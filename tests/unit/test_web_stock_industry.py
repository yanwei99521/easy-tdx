"""股票所属行业接口测试（离线，使用假的 MAC 客户端）。"""

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from easy_tdx.web.routers.stock_industry import router  # noqa: E402


class _FakeMacClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[int, str]] = []

    async def get_belong_board(self, market: int, code: str) -> pd.DataFrame:
        self.calls.append((market, code))
        return pd.DataFrame(self.rows)


def _client(fake: _FakeMacClient) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.mac_client = fake
    return TestClient(app)


def test_stock_industry_returns_industries_and_daily_change_pct() -> None:
    fake = _FakeMacClient(
        [
            {
                "board_type": 12,
                "board_code": "881130",
                "board_name": "酿酒",
                "close": 110.0,
                "pre_close": 100.0,
            },
            {
                "board_type": 5,
                "board_code": "880821",
                "board_name": "大盘股",
                "close": 105.0,
                "pre_close": 100.0,
            },
            {
                "board_type": 0,
                "board_code": "881200",
                "board_name": "食品饮料",
                "close": 99.0,
                "pre_close": 100.0,
            },
        ]
    )
    with _client(fake) as client:
        response = client.get(
            "/api/v1/stock/industry",
            params={"market": "SH", "code": "600519"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["data"] == [
        {
            "market": "SH",
            "code": "600519",
            "industry_code": "881130",
            "industry_name": "酿酒",
            "board_type": 12,
            "close": 110.0,
            "pre_close": 100.0,
            "change_pct": 10.0,
        },
        {
            "market": "SH",
            "code": "600519",
            "industry_code": "881200",
            "industry_name": "食品饮料",
            "board_type": 0,
            "close": 99.0,
            "pre_close": 100.0,
            "change_pct": -1.0,
        },
    ]
    assert fake.calls == [(1, "600519")]


def test_stock_industry_handles_zero_pre_close_and_empty_result() -> None:
    fake = _FakeMacClient(
        [
            {
                "board_type": 1,
                "board_code": "881201",
                "board_name": "食品饮料二级",
                "close": 99.0,
                "pre_close": 0.0,
            },
            {
                "board_type": 4,
                "board_code": "880564",
                "board_name": "白酒概念",
                "close": 110.0,
                "pre_close": 100.0,
            },
        ]
    )
    with _client(fake) as client:
        response = client.get(
            "/api/v1/stock/industry",
            params={"market": "SZ", "code": "000001"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "market": "SZ",
                "code": "000001",
                "industry_code": "881201",
                "industry_name": "食品饮料二级",
                "board_type": 1,
                "close": 99.0,
                "pre_close": 0.0,
                "change_pct": None,
            }
        ],
        "count": 1,
    }


def test_stock_industry_validates_code_length() -> None:
    fake = _FakeMacClient([])
    with _client(fake) as client:
        response = client.get(
            "/api/v1/stock/industry",
            params={"market": "SH", "code": "60051"},
        )

    assert response.status_code == 422
    assert fake.calls == []


def test_stock_industry_fetches_membership_on_each_request() -> None:
    """行业归属不应复用跨请求缓存，交易日变化时可获得最新数据。"""
    fake = _FakeMacClient(
        [
            {
                "board_type": 12,
                "board_code": "881130",
                "board_name": "酿酒",
                "close": 110.0,
                "pre_close": 100.0,
            }
        ]
    )
    with _client(fake) as client:
        params = {"market": "SH", "code": "600519"}
        first = client.get("/api/v1/stock/industry", params=params)
        second = client.get("/api/v1/stock/industry", params=params)

    assert first.status_code == 200
    assert second.status_code == 200

    assert fake.calls == [(1, "600519"), (1, "600519")]
