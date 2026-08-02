from dotenv import load_dotenv
load_dotenv(override=True)  # Load environment variables from .env file

import os
import logging
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app import models
from app.database import engine


def _build_csp(nonce: str = None) -> str:
    """Build Content-Security-Policy header value."""
    style_src = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    return (
        "default-src 'self'; "
        "script-src 'self'; "
        f"style-src {style_src}; "
        "font-src 'self'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://accounts.google.com https://login.microsoftonline.com https://*.microsoftonline.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses to mitigate common web vulnerabilities."""

    async def dispatch(self, request: Request, call_next):
        # Generate a per-request nonce for CSP style-src (used by MUI/emotion)
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Prevent XSS in older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Permissions policy (restrict browser features)
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # Enable HTTP Strict Transport Security
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Set CSP with nonce for HTML responses, without nonce for API responses
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Content-Security-Policy"] = _build_csp(nonce)
        else:
            response.headers["Content-Security-Policy"] = _build_csp()

        return response

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Import all routers
from app.routers import (
    analytics,
    admin,
    batches,
    scheduled_tasks,
    help,
    tasks,
    auth,
    users,
    queries,
    responses,
    competitors,
    descriptors,
    reports,
    exports,  # Period-scoped spreadsheet exports
    investigations,  # Agentic "why did this change" analysis
    brands,
    operations,
    tenants,
    migration_helper,  # Temporary migration helper
    llm_providers,  # LLM Provider configuration for Lab deployments
    site,  # Site configuration and branding for Lab deployments
    highlights,  # Periodic highlights emails (monthly/quarterly)
)

# This line ensures tables are created if they don't exist when the app starts.
# It's convenient for development. For production, you'd use a migration tool.
models.Base.metadata.create_all(bind=engine)

# Auto-add columns that were added after initial table creation.
# create_all() won't ALTER existing tables — only creates missing ones.
from sqlalchemy import inspect, text
_inspector = inspect(engine)
if "llm_providers" in _inspector.get_table_names():
    _existing_cols = {c["name"] for c in _inspector.get_columns("llm_providers")}
    if "bing_connection_name" not in _existing_cols:
        with engine.begin() as _conn:
            _conn.execute(text("ALTER TABLE llm_providers ADD COLUMN bing_connection_name VARCHAR(200)"))
if "brand_info" in _inspector.get_table_names():
    _existing_cols = {c["name"] for c in _inspector.get_columns("brand_info")}
    if "fiscal_year_start_month" not in _existing_cols:
        with engine.begin() as _conn:
            _conn.execute(text("ALTER TABLE brand_info ADD COLUMN fiscal_year_start_month INTEGER NOT NULL DEFAULT 1"))
if "responses" in _inspector.get_table_names() and engine.dialect.name == "postgresql":
    with engine.begin() as _conn:
        _conn.execute(text("ALTER TABLE responses ALTER COLUMN platform TYPE VARCHAR(100)"))
del _inspector

# --- Lifespan (startup / shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    from app.scheduler import start_scheduler, stop_scheduler

    # --- Startup ---
    from app.database import SessionLocal
    from datetime import datetime
    import app.models as _models

    db = SessionLocal()
    try:
        running_tasks = db.query(_models.TaskStatus).filter(
            _models.TaskStatus.status == "running"
        ).all()

        if running_tasks:
            print(f"\n🔧 Startup cleanup: Found {len(running_tasks)} tasks stuck in 'running' state")
            for task in running_tasks:
                if task.started_at:
                    runtime = datetime.utcnow() - task.started_at
                    runtime_hours = runtime.total_seconds() / 3600
                    task.status = "failed"
                    task.completed_at = datetime.utcnow()
                    deployment_msg = f"Server restarted during task execution (task was running for {runtime_hours:.1f} hours). This typically happens during deployments."
                    if task.error_message:
                        task.error_message = f"{task.error_message}\n\n{deployment_msg}"
                    else:
                        task.error_message = deployment_msg
                    print(f"   • Task #{task.id} ({task.task_type}) - marked as failed (was running for {runtime_hours:.1f}h)")
            db.commit()
            print(f"✅ Cleanup complete: {len(running_tasks)} stale tasks marked as failed\n")
        else:
            print("✅ No stale running tasks found on startup\n")
    except Exception as e:
        print(f"⚠️  Warning: Failed to clean up stale tasks on startup: {e}")
        db.rollback()
    finally:
        db.close()

    print("\n📅 Checking scheduler configuration...")
    start_scheduler()
    print("✅ Scheduler check complete\n")

    yield  # Application runs here

    # --- Shutdown ---
    stop_scheduler()


# Create the FastAPI app instance
app = FastAPI(
    title="Tales",
    description="An AI tool for tracking and analyzing LLM brand depictions.",
    version="2.0.0",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Import for exception handling
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException

# Add exception handler to ensure CORS headers on all responses
@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    """Add CORS headers to error responses"""
    origin = request.headers.get("origin")

    # List of allowed origins (must match CORS config below)
    allowed_origins = _build_allowed_origins()

    headers = {}
    if origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers
    )

# Build CORS origins list.
#
# Configure via environment variables:
#   ENVIRONMENT      - set to "production" to drop the localhost dev origins
#   FRONTEND_URL     - the primary frontend URL (e.g., https://tales.mylab.gov)
#   ALLOWED_ORIGINS  - additional origins, comma-separated (optional)
#
# Localhost dev origins are included outside production so local Vite dev
# servers work. They are dropped in production because the CORS policy is
# credentialed, and a deployment should not accept credentialed requests from
# an origin it does not actually serve.
def _build_allowed_origins() -> list[str]:
    if os.environ.get("ENVIRONMENT", "development").strip().lower() == "production":
        origins = []
    else:
        origins = [
            "http://localhost:5173",  # Vite default dev port
            "http://localhost:5177",  # Vite alternate dev port
            "http://localhost:8080",  # Default docker-compose port
        ]
    frontend_url = os.environ.get("FRONTEND_URL")
    if frontend_url and frontend_url not in origins:
        origins.append(frontend_url)
    extra = os.environ.get("ALLOWED_ORIGINS", "")
    for o in (x.strip() for x in extra.split(",")):
        if o and o not in origins:
            origins.append(o)
    return origins


cors_origins = _build_allowed_origins()

if not cors_origins:
    # Fine for the standard single-container deployment, where the frontend is
    # served from this same origin and never makes a cross-origin request.
    logging.getLogger(__name__).info(
        "No CORS origins configured. If the frontend is hosted separately, set "
        "FRONTEND_URL or ALLOWED_ORIGINS or its requests will be blocked."
    )

# Configure CORS to allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Add security headers to all responses
app.add_middleware(SecurityHeadersMiddleware)

# Include all routers
# Core functionality routers
app.include_router(auth.router)
app.include_router(users.admin_router)
app.include_router(users.invitation_router)
app.include_router(tenants.router)
app.include_router(queries.router)
app.include_router(responses.router)
app.include_router(competitors.router)
app.include_router(descriptors.router)
app.include_router(brands.router_brands)
app.include_router(brands.router_brand_info)
app.include_router(reports.router)
app.include_router(reports.how_tales_works_router)
app.include_router(exports.router)
app.include_router(investigations.router)
app.include_router(operations.router)

# Analytics and admin routers
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(llm_providers.router)  # LLM Provider configuration
app.include_router(site.router)  # Site branding configuration
app.include_router(batches.router)
app.include_router(scheduled_tasks.router)
app.include_router(help.router)
app.include_router(tasks.router)
app.include_router(highlights.router)  # Periodic highlights emails

# Temporary migration helper (will be removed after rollback)
app.include_router(migration_helper.router)

# --- Health Check ---
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for monitoring and container orchestration."""
    return {"status": "healthy"}

# --- Static Files & Frontend ---
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# Only mount static files if the dist directory exists (production)
if FRONTEND_DIST.exists():
    # Mount static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    # Serve other static files from dist root
    # NOTE: This must be defined AFTER all API routers to avoid intercepting API calls
    # Cache the index.html template for nonce injection
    _index_html_template = (FRONTEND_DIST / "index.html").read_text()

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        """Serve the React frontend for all non-API routes"""
        from fastapi.responses import FileResponse, HTMLResponse
        from fastapi import HTTPException

        # List of API path prefixes that should NOT be served by frontend
        # These are handled by FastAPI routers and should return 404 if not found
        api_prefixes = (
            "api/",
            "auth/",
            "admin/",
            "brands/",
            "brand-info/",
            "queries/",
            "responses/",
            "competitors/",
            "descriptors/",
            "reports/",
            "operations/",
            "tenants/",
            "batches/",
            "scheduled-tasks/",
            "help/",
            "tasks/",
            "docs",
            "openapi.json",
            "redoc",
        )

        if full_path.startswith(api_prefixes):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        # Block cloud metadata paths to prevent SSRF/metadata attacks
        cloud_metadata_prefixes = (
            "computemetadata",
            "metadata",
            "latest/meta-data",
            "latest/user-data",
            "latest/dynamic",
        )
        if full_path.lower().startswith(cloud_metadata_prefixes):
            raise HTTPException(status_code=403, detail="Forbidden")

        # Path traversal protection: resolve the path and verify it stays
        # within FRONTEND_DIST to prevent directory traversal attacks
        try:
            file_path = (FRONTEND_DIST / full_path).resolve()
            frontend_root = FRONTEND_DIST.resolve()
            if not str(file_path).startswith(str(frontend_root)):
                raise HTTPException(status_code=400, detail="Invalid path")
        except (ValueError, OSError):
            raise HTTPException(status_code=400, detail="Invalid path")

        # Try to serve the specific file if it exists
        if file_path.is_file():
            return FileResponse(file_path)

        # Serve index.html with CSP nonce injected for MUI/emotion styles
        nonce = getattr(request.state, "csp_nonce", "")
        html = _index_html_template.replace(
            "<head>",
            # nonce is generated server-side by SecurityHeadersMiddleware via
            # secrets.token_urlsafe(16). No request-controlled data is interpolated.
            # nosemgrep: python.django.security.injection.raw-html-format.raw-html-format
            f'<head>\n    <meta name="emotion-nonce" content="{nonce}">',
        )
        return HTMLResponse(content=html)
else:
    # Development fallback - API only
    @app.get("/", tags=["Root"])
    async def read_root():
        """Root endpoint to check if the API is running."""
        return {"message": "Welcome to the TALES API! Frontend not built yet."}
