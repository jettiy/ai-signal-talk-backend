"""AI 시그널 생성 라우터 — Z.AI GLM-5 주력 + 기존 폴백"""
import os
import httpx
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import models, database, uuid

router = APIRouter()

ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
MINIMAX_KEY = os.getenv("MINIMAX_API_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")


class SignalRequest(BaseModel):
    symbol: str
    price: float
    changePct: float
    news: list[dict] = []


class SignalResponse(BaseModel):
    entryPrice: float
    targetPrice: float
    stopLoss: float
    confidence: int
    rationale: str
    timeframe: str
    signalType: str  # LONG / SHORT
    model: str


def build_prompt(symbol: str, price: float, change_pct: float, news: list[dict]) -> str:
    news_txt = "\n".join([f"- {n.get('title','')}" for n in news[:3]]) or "暂无新闻"
    return (
        f"너는 한국 전문 트레이더 AI分析师다.\n"
        f"종목: {symbol} | 현재가: ${price} | 전일대비: {change_pct:+.2f}%\n"
        f"뉴스: {news_txt}\n"
        f"아래 JSON만 응답:\n"
        f'{{"entryPrice":숫자,"targetPrice":숫자,"stopLoss":숫자,"confidence":0~100숫자,'
        f'"rationale":"한국어2~3문장","timeframe":"단기/중기","signalType":"LONG또는SHORT"}}'
    )


async def call_zai(url: str, headers: dict, body: dict) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.json()
    except: return None


def parse_response(data: dict, model_name: str) -> SignalResponse:
    try:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        import re
        m = re.search(r'\{[\s\S]*\}', content)
        if m:
            d = eval(m.group())
            return SignalResponse(
                entryPrice=float(d["entryPrice"]), targetPrice=float(d["targetPrice"]),
                stopLoss=float(d["stopLoss"]), confidence=int(d["confidence"]),
                rationale=d["rationale"], timeframe=d.get("timeframe","단기"),
                signalType=d["signalType"], model=model_name,
            )
    except: pass
    # 폴백
    return _fallback(model_name)


def _fallback(model: str) -> SignalResponse:
    return SignalResponse(entryPrice=100.0, targetPrice=103.0, stopLoss=97.0,
        confidence=60, rationale="AI 분석 결과를 생성 중입니다.", timeframe="단기", signalType="LONG", model=model)


@router.post("/", response_model=SignalResponse)
async def generate_signal(body: SignalRequest, db: Session = Depends(database.get_db)):
    prompt = build_prompt(body.symbol, body.price, body.changePct, body.news)

    tasks = []
    # Z.AI GLM-5 주력
    if ZAI_API_KEY:
        tasks.append(call_zai(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            {"Authorization": f"Bearer {ZAI_API_KEY}", "Content-Type": "application/json"},
            {"model": "glm-5", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024, "temperature": 0.7}
        ))
    # MiniMax
    if MINIMAX_KEY:
        tasks.append(call_zai(
            "https://api.minimax.chat/v1/text/chatcompletion_pro",
            {"Authorization": f"Bearer {MINIMAX_KEY}", "Content-Type": "application/json"},
            {"model": "MiniMax-Text-01", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
        ))
    # DeepSeek
    if DEEPSEEK_KEY:
        tasks.append(call_zai(
            "https://api.deepseek.com/v1/chat/completions",
            {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
            {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
        ))
    # OpenAI
    if OPENAI_KEY:
        tasks.append(call_zai(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            {"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
        ))

    model_names = ["Z.AI GLM-5", "MiniMax MiMo", "DeepSeek", "GPT-4o"]
    for i, r in enumerate(results):
        if isinstance(r, dict) and r.get("choices"):
            signal = parse_response(r, model_names[i])
            # DB 저장
            db.add(models.AiSignal(
                id=str(uuid.uuid4()), symbol=body.symbol,
                entry_price=signal.entryPrice, target_price=signal.targetPrice,
                stop_loss=signal.stopLoss, confidence=signal.confidence,
                rationale=signal.rationale, signal_type=signal.signalType,
                timeframe=signal.timeframe, model=signal.model,
            ))
            db.commit()
            return signal

    # 모두 실패
    return _fallback("Fallback")


@router.get("/history/{symbol}")
async def signal_history(symbol: str, db: Session = Depends(database.get_db)):
    signals = db.query(models.AiSignal).filter(
        models.AiSignal.symbol == symbol
    ).order_by(models.AiSignal.created_at.desc()).limit(20).all()
    return signals
