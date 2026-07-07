"""
Database setup — async SQLAlchemy with SQLite.

We use async so that long-running sslyze scans
don't block the event loop for other requests.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.DATABASE_URL,
    # SQLite needs this to allow multiple concurrent readers
    connect_args={"check_same_thread": False},
    echo=False,  # Set True to see SQL in console during debugging
)

# Session factory — each request gets its own session via dependency injection
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Base model class — all ORM models inherit from this
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

async def init_db():
    """Create all tables. Safe to call multiple times — only creates if missing."""
    async with engine.begin() as conn:
        # Import models so SQLAlchemy knows about them before creating tables
        import app.models.scan  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Dependency — use in FastAPI route functions
# ---------------------------------------------------------------------------

async def get_db() -> AsyncSession:
    """
    Yields a database session for a single request.
    Automatically closes when the request is done.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    async with async_session() as session:
        yield session
