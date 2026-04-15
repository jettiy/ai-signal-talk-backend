"""뉴스 라우터"""
import os
import httpx
import time
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
FMP_KEY = os.getenv("FMP_API_KEY", "")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
_CACHE, _TTL = {}, {}

class NewsItem(BaseModel):
    title: str; text: str; source: str; publishedDate: str
    url: str = "#"; symbol: str = ""

@router.get("/")
async def get_news(limit: int = Query(20)):
    key = f"news_{limit}"
    if key in _CACHE and (time.time() - _TTL.get(key, 0)) < 30:
        return _CACHE[key]
    items = []
    # FMP 뉴스
    if FMP_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"https://financialmodelingprep.com/api/v3/stock_news?limit={limit}&apikey={FMP_KEY}")
                r.raise_for_status()
                for d in r.json()[:limit]:
                    items.append(NewsItem(**d))
        except: pass
    # 모의 데이터 (없으면)
    if not items:
        items = [
            NewsItem(title="美 Fed, 금리 동결 유지 — 2026년 인하 기대 여부 논쟁", text="연준은 기준금리를 현 수준으로 유지하겠다고 밝혔다.", source="Reuters", publishedDate="2026-04-15"),
            NewsItem(title="WTI 원유 93달러대 — 호르만자 해협 긴장 지속", text="이란-미국 협상 진행 속에서 원유 공급 불안이 이어지고 있다.", source="Bloomberg", publishedDate="2026-04-15"),
            NewsItem(title="엔비디아, AI 칩 수요 급증으로 사상 최대 실적 기대", text="AI数据中心 확장으로 GPU 매출이 폭발적 증가세를 보이고 있다.", source="CNBC", publishedDate="2026-04-15"),
            NewsItem(title="코스피 6,000선 회복 — 외국인 매수 급증", text="美·이란 휴전 협상 기대감에 기관·외국인 동반 매수세 유입.", source="Reuters", publishedDate="2026-04-15"),
        ]
    _CACHE[key] = items; _TTL[key] = time.time()
    return items
