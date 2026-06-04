import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker


def _with_postgres_ssl(url: str) -> str:
    if not url.startswith("postgresql") or "sslmode" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=require"


def _database_url_from_env() -> str:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return _with_postgres_ssl(database_url)

    db_user = os.environ.get("DB_USER", "")
    db_password = os.environ.get("DB_PASSWORD", "")
    db_host = os.environ.get("DB_HOST", "")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "")
    if db_user and db_password and db_host and db_name:
        return _with_postgres_ssl(
            f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        )

    return "sqlite:///./ai_signal_talk.db"


DATABASE_URL = _database_url_from_env()
print(f"[DB] Connecting to: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")

if DATABASE_URL.startswith("postgresql"):
    try:
        engine = create_engine(DATABASE_URL, pool_size=5, pool_recycle=300, pool_pre_ping=True)
        # 연결 테스트
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[DB] PostgreSQL 연결 성공!")
    except Exception as e:
        print(f"[DB] PostgreSQL 연결 실패: {e}")
        print(f"[DB] SQLite로 폴백합니다.")
        engine = create_engine("sqlite:///./ai_signal_talk.db", connect_args={"check_same_thread": False})
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
