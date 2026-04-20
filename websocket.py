import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session
from database import get_db
from models import User, Conversation, Message
from auth import get_current_user
import json


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        # active_connections: user_id -> WebSocket
        self.active_connections: Dict[int, WebSocket] = {}
        # user_rooms: user_id -> set of room_ids
        self.user_rooms: Dict[int, Set[int]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        """WebSocket 연결"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_rooms.setdefault(user_id, set())
        print(f"WebSocket 연결됨: user_id={user_id}")

    def disconnect(self, user_id: int):
        """WebSocket 연결 종료"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_rooms:
            del self.user_rooms[user_id]
        print(f"WebSocket 연결 종료: user_id={user_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        """개인 메시지 전송"""
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

    async def broadcast(self, message: dict, room_id: Optional[int] = None):
        """방 전체 메시지 전송"""
        if room_id is None:
            # 모든 연결에 전송
            for user_id, connection in self.active_connections.items():
                await connection.send_json(message)
        else:
            # 특정 방에 연결된 사용자만 전송
            for user_id, rooms in self.user_rooms.items():
                if room_id in rooms:
                    if user_id in self.active_connections:
                        await self.active_connections[user_id].send_json(message)


manager = ConnectionManager()


async def handle_websocket(
    websocket: WebSocket,
    db: Session,
    token: str
):
    """WebSocket 핸들러"""
    # 인증
    try:
        user = await get_current_user(token, db)
        user_id = user.id
    except:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 연결
    await manager.connect(websocket, user_id)

    try:
        while True:
            # 메시지 수신
            data = await websocket.receive_text()
            message_data = json.loads(data)

            msg_type = message_data.get("type")
            content = message_data.get("content", "")

            # 메시지 저장
            conversation_id = message_data.get("conversation_id")
            if conversation_id:
                # 기존 대화 찾기
                conversation = db.query(Conversation).filter(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id
                ).first()

                if conversation:
                    # 새 메시지 생성
                    new_message = Message(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        role="user",
                        content=content
                    )
                    db.add(new_message)
                    db.commit()

                    # 방 전체에 브로드캐스트
                    await manager.broadcast({
                        "type": "message",
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "role": "user",
                        "content": content,
                        "timestamp": new_message.created_at.isoformat()
                    }, room_id=conversation_id)

                    # AI 응답 생성 (나중에 구현)
                    # await generate_ai_response(websocket, conversation_id, user_id, content)
                else:
                    # 대화가 없으면 새 대화 생성
                    new_conversation = Conversation(
                        user_id=user_id,
                        title=content[:50] + "..." if len(content) > 50 else content
                    )
                    db.add(new_conversation)
                    db.flush()

                    new_message = Message(
                        conversation_id=new_conversation.id,
                        user_id=user_id,
                        role="user",
                        content=content
                    )
                    db.add(new_message)
                    db.commit()

                    await manager.broadcast({
                        "type": "conversation_created",
                        "conversation_id": new_conversation.id,
                        "title": new_conversation.title,
                        "timestamp": new_conversation.created_at.isoformat()
                    }, room_id=new_conversation.id)

                    # 방에 사용자 추가
                    if user_id not in manager.user_rooms:
                        manager.user_rooms[user_id] = set()
                    manager.user_rooms[user_id].add(new_conversation.id)

                    await manager.broadcast({
                        "type": "message",
                        "conversation_id": new_conversation.id,
                        "user_id": user_id,
                        "role": "user",
                        "content": content,
                        "timestamp": new_message.created_at.isoformat()
                    }, room_id=new_conversation.id)
            else:
                # 개인 메시지
                await manager.send_personal_message({
                    "type": "error",
                    "message": "conversation_id가 필요합니다."
                }, user_id)

    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"WebSocket 에러: {e}")
        manager.disconnect(user_id)
