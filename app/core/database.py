import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")


def get_db_url_with_ssl(url: str) -> str:
    """Ensure SSL parameters are added for PostgreSQL connections"""
    if "postgresql" in url.lower():
        if "?" not in url:
            url += "?sslmode=require"
        elif "sslmode" not in url:
            url += "&sslmode=require"
    return url


DATABASE_URL = get_db_url_with_ssl(DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=120,
    pool_size=2,  # CHANGED — was 5
    max_overflow=1,  # CHANGED — was 10
    pool_timeout=30,
    echo=False,
    connect_args=(
        {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "connect_timeout": 10,
        }
        if "postgresql" in DATABASE_URL
        else {}
    ),
)


@event.listens_for(engine, "connect")
def set_isolation_level(dbapi_connection, connection_record):
    """Set isolation level and search path for new connections"""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("SET search_path TO public")
        cursor.close()
    except Exception as e:
        logger.warning(f"Error setting isolation level: {e}")


@event.listens_for(engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    """Log when a connection is checked out (for debugging)"""
    logger.debug(f"Connection checked out: {dbapi_connection}")


@event.listens_for(engine, "invalidate")
def on_invalidate(dbapi_connection, connection_record, exception):
    """Log when a connection is invalidated"""
    logger.warning(f"Connection invalidated: {exception}")


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """Dependency for FastAPI routes to get a database session"""
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_db: {e}")
        db.rollback()
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"Error closing database session: {e}")


from contextlib import contextmanager


@contextmanager
def get_db_context():
    """Context manager for database sessions (for background tasks)"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database error in context: {e}")
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"Error closing session in context: {e}")
