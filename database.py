import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1순위: 개별 DB 환경변수 조합 (비밀번호 마스킹 문제 회피)
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "")

if DB_USER and DB_PASSWORD and DB_HOST:
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=require"
else:
    # 2순위: DATABASE_URL 환경변수 (마스킹 체크)
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./ai_signal_talk.db")
    if "***" in DATABASE_URL:
        DATABASE_URL = "sqlite:///./ai_signal_talk.db"
    if DATABASE_URL.startswith("postgresql"):
        if "sslmode" not in DATABASE_URL:
            separator = "&" if "?" in DATABASE_URL else "?"
            DATABASE_URL += f"{separator}sslmode=require"

if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(DATABASE_URL, pool_size=5, pool_recycle=300)
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
