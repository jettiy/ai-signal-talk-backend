"""
DB 스키마 리셋 스크립트 — 기존 테이블 DROP 후 재생성
"""
import os
import sys

# 환경변수 설정 (database.py 임포트 전에 필요)
os.environ.setdefault("DB_USER", "signaltalk2")
os.environ.setdefault("DB_PASSWORD", "oRFzqEdWcbiyzQuIr6Ylxtd9VmJbYCQ9")
os.environ.setdefault("DB_HOST", "dpg-d7imkh9j2pic73auslf0-a")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "ai_signal_talk")

from database import engine, Base, DATABASE_URL
from models import User, Conversation, Message, SignalHistory

print(f"DB URL (masked): {DATABASE_URL[:30]}...")

# 기존 테이블 삭제
print("기존 테이블 삭제 중...")
Base.metadata.drop_all(bind=engine)
print("삭제 완료")

# 새 테이블 생성
print("새 테이블 생성 중...")
Base.metadata.create_all(bind=engine)
print("생성 완료")

# 관리자 계정 생성
from auth import get_password_hash
from sqlalchemy.orm import Session
session = Session(bind=engine)
try:
    admin = User(
        email="admin@signaltalk.ai",
        hashed_password=get_password_hash("admin123!"),
        nickname="관리자",
        role="ADMIN",
        is_active=1,
    )
    session.add(admin)
    session.commit()
    print(f"관리자 계정 생성: admin@signaltalk.ai / admin123!")
except Exception as e:
    print(f"관리자 생성 스킵 (이미 존재): {e}")
finally:
    session.close()

print("✅ DB 리셋 완료!")
