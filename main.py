"""
AI 시그널톡 — FastAPI 백엔드
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="AI 시그널톡 API",
    description="실시간 투자 시그널 & 트레이더 커뮤니티 백엔드",
    version="1.0.0",
)

# CORS — Vercel 프론트엔드 허용
origins = [
    "https://ai-signal-talk.vercel.app",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 임포트
from routers import auth, market, news, ai_signal, chat, pro_application

app.include_router(auth.router, prefix="/api/auth", tags=["인증"])
app.include_router(market.router, prefix="/api/market", tags=["시세"])
app.include_router(news.router, prefix="/api/news", tags=["뉴스"])
app.include_router(ai_signal.router, prefix="/api/ai-signal", tags=["AI 시그널"])
app.include_router(chat.router, prefix="/api/chat", tags=["채팅"])
app.include_router(pro_application.router, prefix="/api/pro", tags=["PRO 상담"])


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
