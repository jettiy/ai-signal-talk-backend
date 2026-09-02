"""시세 라우터"""
import os
import httpx
import time
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
FMP_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com/stable"  # stable API 사용
_CACHE, _TTL = {}, {}

class Quote(BaseModel):
    symbol: str; price: float; change: float; changePct: float
    high52w: float; low52w: float; volume: int; marketCap: Optional[float]=None
    pe: Optional[float]=None; exchange: str="NASDAQ"

async def fetch(symbols: list[str]) -> list[Quote]:
    if not FMP_KEY:
        return _mock()
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{FMP_BASE}/quote?symbol={','.join(symbols)}&apikey={FMP_KEY}")
            r.raise_for_status()
            data = r.json()
            if not data:
                return _mock()
            return [Quote(**d, symbol=d["symbol"], change=float(d.get("change", 0)), changePct=float(d.get("changesPercentage", 0)), high52w=float(d.get("yearHigh", 0)), low52w=float(d.get("yearLow", 0)), volume=int(d.get("volume", 0)), marketCap=float(d.get("marketCap", 0) or 0), pe=float(d.get("pe", 0) or 0), exchange=d.get("exchange", "NASDAQ")) for d in data]
    except:
        return _mock()

def _mock() -> list[Quote]:
    return [Quote(symbol=s, price=p, change=c, changePct=cp, high52w=h, low52w=l, volume=v, exchange=e) for s,p,c,cp,h,l,v,e in [
        ("NQ",18542.5,+77.8,+0.42,19500,15200,320000,"CME"),
        ("GC",2034.2,-3.6,-0.18,2200,1800,180000,"COMEX"),
        ("CL",77.84,+0.24,+0.31,124,65,420000,"NYMEX"),
        ("SPY",522.18,+4.51,+0.87,540,460,78000000,"NYSE"),
        ("NVDA",875.32,+29.21,+3.45,974,495,38000000,"NASDAQ"),
    ]]

@router.get("/quotes")
async def quotes(symbols: str = Query("NQ,GC,CL")):
    syms = [s.strip() for s in symbols.split(",")]
    key = ",".join(sorted(syms))
    if key in _CACHE and (time.time() - _TTL.get(key, 0)) < 10:
        return _CACHE[key]
    data = await fetch(syms)
    _CACHE[key] = data; _TTL[key] = time.time()
    return data

@router.get("/quote/{symbol}")
async def quote(symbol: str):
    results = await fetch([symbol])
    if not results: raise HTTPException(404, "종목을 찾을 수 없습니다.")
    return results[0]
