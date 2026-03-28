"""
AutoPoster Admin Dashboard — FastAPI Application

Run: uvicorn dashboard.main:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys

# Add project root to path so we can import src.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from dashboard.database import init_db
from dashboard.routers import overview, posts, pipeline, sources, analytics, logs, settings, auth, auth_user
from dashboard.routers.auth_user import get_current_user
from fastapi import Depends

app = FastAPI(title="AutoPoster Admin", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cloudflare Worker Middleware (optional but useful for D1)
@app.middleware("http")
async def cloudflare_middleware(request: Request, call_next):
    """Capture Cloudflare environment on each request."""
    # Cloudflare Workers Python environment is passed in request.scope["env"]
    env = request.scope.get("env")
    if env:
        from dashboard.database import set_d1_binding, set_r2_binding
        if hasattr(env, "DB"):
            set_d1_binding(env.DB)
        if hasattr(env, "BUCKET"):
            set_r2_binding(env.BUCKET)
    return await call_next(request)

# Mount static directories (Conditional for Worker)
images_dir = os.path.join(PROJECT_ROOT, "data", "images")
if not os.getenv("CLOUDFLARE_WORKER"):
    os.makedirs(images_dir, exist_ok=True)
    app.mount("/images", StaticFiles(directory=images_dir), name="images")

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.getenv("CLOUDFLARE_WORKER"):
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include public routers
# ... (rest of routers remains)
app.include_router(auth_user.router)
app.include_router(auth.router)

# Include protected routers
auth_deps = [Depends(get_current_user)]
app.include_router(overview.router, dependencies=auth_deps)
app.include_router(posts.router, dependencies=auth_deps)
app.include_router(pipeline.router, dependencies=auth_deps)
app.include_router(sources.router, dependencies=auth_deps)
app.include_router(analytics.router, dependencies=auth_deps)
app.include_router(logs.router, dependencies=auth_deps)
app.include_router(settings.router, dependencies=auth_deps)

@app.on_event("startup")
def startup():
    """Run DB migrations on startup. Safety check for Worker."""
    if not os.getenv("CLOUDFLARE_WORKER"):
        init_db()


@app.get("/")
def serve_dashboard():
    """Serve the dashboard SPA."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
