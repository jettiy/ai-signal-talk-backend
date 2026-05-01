import os

from sqlalchemy import create_engine
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
