import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Get the absolute path of the project's root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Get database URL from environment variable, or default to SQLite for local development
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Default to SQLite for local development
    DATABASE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'tales.db')}"

# Handle Render's postgres:// URL format (needs to be postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Create the SQLAlchemy engine
# connect_args is needed only for SQLite to allow it to be used by multiple threads
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL - increase connection pool to handle concurrent requests
    # pool_size: number of connections to keep open
    # max_overflow: additional connections that can be created on demand
    # pool_pre_ping: verify connections are alive before using them
    # pool_recycle: recycle connections after 1 hour to prevent stale connections
    # TCP keepalives (libpq parameters, honored by psycopg2 and psycopg) so a
    # connection that sits idle survives network gear that drops quiet TCP
    # sessions (Docker Swarm's IPVS load balancer defaults to a 15-minute idle
    # timeout). pool_pre_ping cannot save a connection already checked out:
    # on 2026-09-14 the scheduler lost one mid-run and the whole collection
    # went unrecorded. Probes start after 5 idle minutes, 30 seconds apart.
    connect_args = {}
    if DATABASE_URL.startswith("postgresql"):
        connect_args = {
            "keepalives": 1,
            "keepalives_idle": 300,
            "keepalives_interval": 30,
            "keepalives_count": 3,
        }
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,          # Increased from default 5
        max_overflow=30,       # Increased from default 10
        pool_pre_ping=True,    # Check connection health
        pool_recycle=3600,     # Recycle after 1 hour
        connect_args=connect_args,
    )

# Create a SessionLocal class. Each instance of this class will be a database session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a Base class. Your ORM models will inherit from this class.
Base = declarative_base()


# Dependency function that provides a database session per request
def get_db():
    """
    Dependency function that provides a database session per request.
    Ensures the session is always closed, even if errors occur.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()