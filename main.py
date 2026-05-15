import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from app.db.init import init_db
from app.db.runner import run_migrations
from app.api import templates, apps, jobs, ws, settings
from app.services.template_sync import sync_templates

STATIC_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    run_migrations()
    result = sync_templates()
    if result.get("ok"):
        added = sum(1 for r in result.get("results", []) if r["status"] == "added")
        unchanged = sum(1 for r in result.get("results", []) if r["status"] == "unchanged")
        print(f"[templates] Sync complete — {added} added, {unchanged} unchanged")
    else:
        print(f"[templates] Sync warning: {result.get('error', 'partial failure')}")
        for err in result.get("errors", []):
            print(f"[templates]   {err['slug']}: {err['error']}")
    yield


app = FastAPI(title="Arrqitect", lifespan=lifespan)

app.include_router(templates.router)
app.include_router(apps.router)
app.include_router(jobs.router)
app.include_router(ws.router)
app.include_router(settings.router)

if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
