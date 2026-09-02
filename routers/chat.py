"""채팅 라우터 — Z.AI GLM-5-Turbo Function Calling"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import models, database, uuid, json

router = APIRouter()

ZAI_API_KEY = database.__dict__.get("ZAI_API_KEY", "")  # 환경변수에서 가져오기
ZAI_AGENT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


class ChatMessageIn(BaseModel):
    content: str
    conversation_id: Optional[str] = None
    nickname: Optional[str] = None


class ChatMessageOut(BaseModel):
    id: str
    nickname: str
    grade: str
    content: str
    is_bot: bool
    created_at: str


def call_zai_chat(messages: list[dict], tools: list[dict] = None) -> dict | None:
    """Z.AI 채팅 API 호출"""
    try:
        import httpx
        headers = {
            "Authorization": f"Bearer {ZAI_API_KEY}",
            "Content-Type": "application/json"
        }
        body = {
            "model": "glm-5-turbo",  # Function Calling 최적화
            "messages": messages,
            "temperature": 0.7,
            "top_p": 0.9
        }
        if tools:
            body["tools"] = tools
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(ZAI_AGENT_URL, headers=headers, json=body)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"Z.AI 채팅 에러: {e}")
        return None


@router.get("/", response_model=list[ChatMessageOut])
async def get_messages(limit: int = 50, db: Session = Depends(database.get_db)):
    msgs = db.query(models.ChatMessage).order_by(
        models.ChatMessage.created_at.desc()
    ).limit(limit).all()
    return list(reversed(msgs))


@router.post("/", response_model=ChatMessageOut)
async def send_message(body: ChatMessageIn, db: Session = Depends(database.get_db)):
    # Z.AI Function Calling 도구 정의
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_quote",
                "description": "종목의 현재가와 변화율 조회",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "종목 심볼 (예: AAPL, NVDA, GCUSD)"}
                    },
                    "required": ["symbol"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_multi_quotes",
                "description": "여러 종목의 시세 조회",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "종목 심볼 리스트 (쉼표로 구분)"
                        }
                    },
                    "required": ["symbols"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_news",
                "description": "종목 뉴스 조회",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "종목 심볼"}
                    },
                    "required": ["symbol"]
                }
            }
        }
    ]

    # 사용자 메시지 저장
    msg = models.ChatMessage(
        id=str(uuid.uuid4()),
        user_id="anonymous",
        nickname=body.nickname or "손님",
        grade="LV.01",
        content=body.content,
        is_bot=False
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Z.AI 에이전트 호출
    messages = [
        {
            "role": "system",
            "content": "너는 AI 시그널톡의 전문 트레이더 채팅봇이다. 사용자의 질문에 대해 도구를 사용해서 답변해줘."
        },
        {
            "role": "user",
            "content": body.content
        }
    ]

    response = call_zai_chat(messages, tools)

    if response and response.get("choices"):
        tool_calls = response["choices"][0].get("message", {}).get("tool_calls")
        if tool_calls:
            # 도구 호출 결과 처리
            for tool_call in tool_calls:
                function_name = tool_call["function"]["name"]
                function_args = json.loads(tool_call["function"]["arguments"])

                # 도구 실행 결과 생성
                tool_result = ""
                if function_name == "get_quote":
                    symbol = function_args["symbol"]
                    # market 라우터에서 가져오기 (실제로는 API 호출 필요)
                    tool_result = f"[시세] {symbol}: $100.00 (+0.00%)"
                elif function_name == "get_multi_quotes":
                    symbols = ",".join(function_args["symbols"])
                    tool_result = f"[시세] {symbols}: $100.00 (+0.00%)"
                elif function_name == "get_news":
                    symbol = function_args["symbol"]
                    tool_result = f"[뉴스] {symbol}에 대한 뉴스를 검색 중입니다."

                # 에이전트 응답 메시지에 도구 결과 추가
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result
                })

            # 최종 응답 호출
            final_response = call_zai_chat(messages)
            if final_response and final_response.get("choices"):
                bot_content = final_response["choices"][0].get("message", {}).get("content", "")

                # 봇 메시지 저장
                bot_msg = models.ChatMessage(
                    id=str(uuid.uuid4()),
                    user_id="bot",
                    nickname="AI 트레이더",
                    grade="LV.99",
                    content=bot_content,
                    is_bot=True
                )
                db.add(bot_msg)
                db.commit()

                return ChatMessageOut(
                    id=bot_msg.id,
                    nickname=bot_msg.nickname,
                    grade=bot_msg.grade,
                    content=bot_msg.content,
                    is_bot=bot_msg.is_bot,
                    created_at=bot_msg.created_at
                )

    # 도구 호출 없으면 기본 응답
    bot_content = "죄송합니다. 현재 AI 채팅 기능을 사용할 수 없습니다. 나중에 다시 시도해주세요."
    bot_msg = models.ChatMessage(
        id=str(uuid.uuid4()),
        user_id="bot",
        nickname="AI 트레이더",
        grade="LV.99",
        content=bot_content,
        is_bot=True
    )
    db.add(bot_msg)
    db.commit()

    return ChatMessageOut(
        id=bot_msg.id,
        nickname=bot_msg.nickname,
        grade=bot_msg.grade,
        content=bot_msg.content,
        is_bot=bot_msg.is_bot,
        created_at=bot_msg.created_at
    )
