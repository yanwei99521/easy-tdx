"""同花顺公开网页的轻量解析客户端。

这不是同花顺官方 API。页面结构、访问策略及字段含义均可能变化，调用方应遵守
同花顺网站规则，并避免高频或商用再分发场景。
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import date
from typing import Any

import httpx

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://basic.10jqka.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
}
_FIELD_URL = "https://basic.10jqka.com.cn/{code}/field.html"
_CONCEPT_URL = "https://basic.10jqka.com.cn/{code}/concept.html"
_INDUSTRY_URL = "https://q.10jqka.com.cn/thshy/"
_CONCEPT_DIRECTORY_URL = "https://q.10jqka.com.cn/gn/"
_BOARD_DETAIL_URLS = {
    "industry": "https://q.10jqka.com.cn/thshy/detail/code/{code}/",
    "concept": "https://q.10jqka.com.cn/gn/detail/code/{code}/",
}
_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE)
_THREE_CATE_RE = re.compile(
    r"三级行业分类：.*?<span[^>]*>\s*(.*?)\s*(?:（|\(|<)", re.IGNORECASE | re.DOTALL
)
_CONCEPT_CELL_RE = re.compile(
    r'<td[^>]*\bclass=["\'][^"\']*\bgnName\b[^"\']*["\'][^>]*\bclid=["\'](\d+)["\'][^>]*>(.*?)</td>',
    re.IGNORECASE | re.DOTALL,
)
_LEADER_CODES_RE = re.compile(
    r'<a\b[^>]*\btopStock=["\']([^"\']*)["\'][^>]*\bcid=["\'](\d+)["\']',
    re.IGNORECASE | re.DOTALL,
)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_BOARD_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'][^"\']*/(?:thshy|gn)/detail/code/(\d+)/[^"\']*["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_STOCK_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'][^"\']*stockpage\.10jqka\.com\.cn/(\d+)/?[^"\']*["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_BOARD_HEADING_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\bboard-hq\b[^"\']*["\'][^>]*>.*?'
    r"<h3[^>]*>.*?<span[^>]*>(\d+)</span>.*?</h3>",
    re.IGNORECASE | re.DOTALL,
)
_BOARD_CHANGE_RE = re.compile(
    r'<p[^>]*\bclass=["\'][^"\']*\bboard-zdf\b[^"\']*["\'][^>]*>.*?'
    r"([+-]?\d+(?:\.\d+)?)%",
    re.IGNORECASE | re.DOTALL,
)


class ThsWebError(RuntimeError):
    """同花顺公开页面请求或解析不可用。"""


def _text(value: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub("", value)).replace("\xa0", " ").split())


def _percent(value: str) -> float | None:
    normalized = _text(value).replace("%", "").replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def parse_industry_hierarchy(page: str) -> list[str]:
    """Extract the THS three-level industry labels from a stock field page."""
    match = _THREE_CATE_RE.search(page)
    if not match:
        return []
    return [part.strip() for part in _text(match.group(1)).split("--") if part.strip()]


def parse_concepts(page: str) -> list[dict[str, Any]]:
    """Extract concept board memberships and THS-exposed leading-stock codes."""
    leader_codes_by_board: dict[str, list[str]] = {}
    for raw_codes, board_code in _LEADER_CODES_RE.findall(page):
        leader_codes_by_board[board_code] = [
            code for code in raw_codes.split(",") if code.isdigit()
        ]

    concepts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for board_code, raw_name in _CONCEPT_CELL_RE.findall(page):
        if board_code in seen:
            continue
        seen.add(board_code)
        concepts.append(
            {
                "board_code": board_code,
                "name": _text(raw_name),
                "leader_codes": leader_codes_by_board.get(board_code, []),
            }
        )
    return concepts


def parse_board_directory(page: str, board_kind: str) -> dict[str, str]:
    """Parse public THS board-directory links into a name-to-code mapping."""
    if board_kind not in {"industry", "concept"}:
        raise ValueError("board_kind must be 'industry' or 'concept'")

    return {_text(raw_name): board_code for board_code, raw_name in _BOARD_LINK_RE.findall(page)}


def parse_board_detail(page: str) -> dict[str, Any] | None:
    """Parse a public THS board detail page and its first ranked constituent."""
    heading = _BOARD_HEADING_RE.search(page)
    change = _BOARD_CHANGE_RE.search(page)
    if not heading or not change:
        return None

    leader: dict[str, Any] | None = None
    for row in _ROW_RE.findall(page):
        cells = _TD_RE.findall(row)
        texts = [_text(cell) for cell in cells]
        stock_links = _STOCK_LINK_RE.findall(row)
        named_stock = next(
            ((code, _text(name)) for code, name in stock_links if _text(name) != code),
            None,
        )
        if not named_stock:
            continue
        stock_code, stock_name = named_stock
        try:
            name_index = texts.index(stock_name)
        except ValueError:
            continue
        leader = {
            "code": stock_code,
            "name": stock_name,
            "change_pct": _percent(texts[name_index + 2]) if len(texts) > name_index + 2 else None,
        }
        break
    return {
        "board_code": heading.group(1),
        "change_pct": _percent(change.group(1)),
        "leader": leader,
    }


class ThsWebClient:
    """Retrieve stock associations from public THS pages with quote-only caching."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        quote_ttl_seconds: float = 30.0,
    ) -> None:
        self._timeout = timeout
        self._transport = transport
        self._quote_ttl_seconds = quote_ttl_seconds
        self._quote_cache: dict[tuple[str, str], tuple[date, float, dict[str, Any] | None]] = {}

    async def _get_page(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                headers=_BROWSER_HEADERS,
                follow_redirects=True,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ThsWebError("同花顺公开页面暂时无法访问") from exc
        return response.content.decode("gbk", errors="replace")

    async def _get_board_detail(self, board_kind: str, board_code: str) -> dict[str, Any] | None:
        """Fetch one board quote, retaining it only briefly within the current day."""
        if board_kind not in _BOARD_DETAIL_URLS:
            raise ValueError("board_kind must be 'industry' or 'concept'")
        today = date.today()
        cache_key = (board_kind, board_code)
        cached = self._quote_cache.get(cache_key)
        if cached and cached[0] == today and time.monotonic() - cached[1] < self._quote_ttl_seconds:
            return cached[2]

        page = await self._get_page(_BOARD_DETAIL_URLS[board_kind].format(code=board_code))
        detail = parse_board_detail(page)
        self._quote_cache[cache_key] = (today, time.monotonic(), detail)
        return detail

    async def _optional_board_detail(
        self, board_kind: str, board_code: str | None
    ) -> dict[str, Any] | None:
        if board_code is None:
            return None
        try:
            return await self._get_board_detail(board_kind, board_code)
        except ThsWebError:
            return None

    async def get_stock_associations(self, code: str, concept_limit: int = 10) -> dict[str, Any]:
        """Get THS industry hierarchy, concept memberships, and public board quotes."""
        pages = await asyncio.gather(
            self._get_page(_FIELD_URL.format(code=code)),
            self._get_page(_CONCEPT_URL.format(code=code)),
            self._get_page(_INDUSTRY_URL),
            self._get_page(_CONCEPT_DIRECTORY_URL),
        )
        field_page, concept_page, industry_directory_page, concept_directory_page = pages
        industry_directory = parse_board_directory(industry_directory_page, "industry")
        concept_directory = parse_board_directory(concept_directory_page, "concept")
        industry_names = parse_industry_hierarchy(field_page)
        all_concepts = parse_concepts(concept_page)
        selected_concepts = all_concepts[:concept_limit]
        detail_semaphore = asyncio.Semaphore(4)

        async def get_limited_detail(
            board_kind: str, board_code: str | None
        ) -> dict[str, Any] | None:
            async with detail_semaphore:
                return await self._optional_board_detail(board_kind, board_code)

        industry_details, concept_details = await asyncio.gather(
            asyncio.gather(
                *(
                    get_limited_detail("industry", industry_directory.get(name))
                    for name in industry_names
                )
            ),
            asyncio.gather(
                *(
                    get_limited_detail("concept", concept_directory.get(concept["name"]))
                    for concept in selected_concepts
                )
            ),
        )

        industries: list[dict[str, Any]] = []
        for level, (name, detail) in enumerate(zip(industry_names, industry_details), start=1):
            industries.append(
                {
                    "level": level,
                    "name": name,
                    "board_code": detail["board_code"] if detail else industry_directory.get(name),
                    "change_pct": detail["change_pct"] if detail else None,
                    "leader": detail["leader"] if detail else None,
                }
            )

        concepts: list[dict[str, Any]] = []
        for concept, detail in zip(selected_concepts, concept_details):
            concepts.append(
                {
                    "board_code": detail["board_code"] if detail else concept["board_code"],
                    "name": concept["name"],
                    "change_pct": detail["change_pct"] if detail else None,
                    "leader": detail["leader"] if detail else None,
                    "leader_codes": concept["leader_codes"],
                }
            )
        return {
            "source": "ths_web",
            "code": code,
            "industries": industries,
            "concepts": concepts,
            "concept_total": len(all_concepts),
        }
