"""同花顺公开网页解析及接口测试。"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from easy_tdx.ths_web import (  # noqa: E402
    ThsWebClient,
    parse_board_detail,
    parse_board_directory,
    parse_concepts,
    parse_industry_hierarchy,
)
from easy_tdx.web.deps import get_ths_web_client  # noqa: E402
from easy_tdx.web.routers.ths import router  # noqa: E402

_FIELD_HTML = """
<p class="threecate fl">三级行业分类：
<span class="tip f14">电子 -- 半导体 -- 数字芯片设计 （共<strong>57</strong>家）</span></p>
"""

_CONCEPT_HTML = """
<table>
  <tr><td class="gnName" clid="301085">芯片概念</td></tr>
  <tr><td class="gnName" clid="308972">比亚迪概念</td></tr>
</table>
<a topStock="002886,003005" cid="301085" tag="芯片概念">芯片概念</a>
<a topStock="300750" cid="308972" tag="比亚迪概念">比亚迪概念</a>
"""

_INDUSTRY_DIRECTORY_HTML = """
<table>
 <tr><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881121/">半导体</a></td></tr>
</table>
"""

_CONCEPT_DIRECTORY_HTML = """
<table><tr><td><a href="http://q.10jqka.com.cn/gn/detail/code/301085/">芯片概念</a></td>
<td><a href="http://q.10jqka.com.cn/gn/detail/code/308972/">比亚迪概念</a></td></tr></table>
"""

_INDUSTRY_DETAIL_HTML = """
<div class="board-hq"><h3>半导体<span>881121</span></h3>
<p class="board-zdf">12.34&nbsp;&nbsp;&nbsp;&nbsp;2.35%</p></div>
<table>
 <tr>
  <td>1</td><td><a href="http://stockpage.10jqka.com.cn/688981/">688981</a></td>
  <td><a href="http://stockpage.10jqka.com.cn/688981/">中芯国际</a></td>
  <td>50.00</td><td>3.21</td>
 </tr>
</table>
"""

_CHIP_DETAIL_HTML = """
<div class="board-hq"><h3>芯片概念<span>301085</span></h3>
<p class="board-zdf">-0.01&nbsp;&nbsp;&nbsp;&nbsp;-0.05%</p></div>
<table><tr><td>1</td><td><a href="http://stockpage.10jqka.com.cn/002886/">002886</a></td>
<td><a href="http://stockpage.10jqka.com.cn/002886/">沃特股份</a></td><td>31.00</td><td>9.50</td></tr></table>
"""

_BYD_DETAIL_HTML = """
<div class="board-hq"><h3>比亚迪概念<span>308972</span></h3>
<p class="board-zdf">0.00&nbsp;&nbsp;&nbsp;&nbsp;0.00%</p></div>
"""


def test_parse_industry_hierarchy() -> None:
    assert parse_industry_hierarchy(_FIELD_HTML) == ["电子", "半导体", "数字芯片设计"]


def test_parse_concepts_extracts_codes_names_and_leading_stock_codes() -> None:
    assert parse_concepts(_CONCEPT_HTML) == [
        {"board_code": "301085", "name": "芯片概念", "leader_codes": ["002886", "003005"]},
        {"board_code": "308972", "name": "比亚迪概念", "leader_codes": ["300750"]},
    ]


def test_parse_board_directory_and_detail_extract_quote_and_leader() -> None:
    assert parse_board_directory(_INDUSTRY_DIRECTORY_HTML, "industry") == {"半导体": "881121"}
    assert parse_board_detail(_INDUSTRY_DETAIL_HTML) == {
        "board_code": "881121",
        "change_pct": 2.35,
        "leader": {"code": "688981", "name": "中芯国际", "change_pct": 3.21},
    }


@pytest.mark.asyncio
async def test_client_merges_stock_membership_and_board_quotes() -> None:
    pages = {
        "/603893/field.html": _FIELD_HTML,
        "/603893/concept.html": _CONCEPT_HTML,
        "/thshy/": _INDUSTRY_DIRECTORY_HTML,
        "/gn/": _CONCEPT_DIRECTORY_HTML,
        "/thshy/detail/code/881121/": _INDUSTRY_DETAIL_HTML,
        "/gn/detail/code/301085/": _CHIP_DETAIL_HTML,
        "/gn/detail/code/308972/": _BYD_DETAIL_HTML,
    }
    calls: dict[str, int] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls[request.url.path] = calls.get(request.url.path, 0) + 1
        return httpx.Response(200, content=pages[request.url.path].encode("gbk"))

    client = ThsWebClient(transport=httpx.MockTransport(handler))
    result = await client.get_stock_associations("603893")

    assert result["code"] == "603893"
    assert result["industries"] == [
        {"level": 1, "name": "电子", "board_code": None, "change_pct": None, "leader": None},
        {
            "level": 2,
            "name": "半导体",
            "board_code": "881121",
            "change_pct": 2.35,
            "leader": {"code": "688981", "name": "中芯国际", "change_pct": 3.21},
        },
        {
            "level": 3,
            "name": "数字芯片设计",
            "board_code": None,
            "change_pct": None,
            "leader": None,
        },
    ]
    assert result["concept_total"] == 2
    assert result["concepts"] == [
        {
            "board_code": "301085",
            "name": "芯片概念",
            "change_pct": -0.05,
            "leader": {"code": "002886", "name": "沃特股份", "change_pct": 9.5},
            "leader_codes": ["002886", "003005"],
        },
        {
            "board_code": "308972",
            "name": "比亚迪概念",
            "change_pct": 0.0,
            "leader": None,
            "leader_codes": ["300750"],
        },
    ]
    await client.get_stock_associations("603893")
    assert calls == {
        "/603893/field.html": 2,
        "/603893/concept.html": 2,
        "/thshy/": 2,
        "/gn/": 2,
        "/thshy/detail/code/881121/": 1,
        "/gn/detail/code/301085/": 1,
        "/gn/detail/code/308972/": 1,
    }


class _FakeThsClient:
    async def get_stock_associations(self, code: str, concept_limit: int) -> dict[str, object]:
        assert concept_limit == 10
        return {"source": "ths_web", "code": code, "industries": [], "concepts": []}


def _api_client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_ths_web_client] = lambda: _FakeThsClient()
    return TestClient(app)


def test_ths_associations_endpoint() -> None:
    with _api_client() as client:
        response = client.get("/api/v1/ths/stock/associations", params={"code": "603893"})

    assert response.status_code == 200
    assert response.json() == {
        "data": {"source": "ths_web", "code": "603893", "industries": [], "concepts": []}
    }


def test_ths_associations_endpoint_validates_code() -> None:
    with _api_client() as client:
        response = client.get("/api/v1/ths/stock/associations", params={"code": "60389"})

    assert response.status_code == 422
