import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from app.db.init import init_db
from app.db.runner import run_migrations
from app.api import templates, apps, jobs, ws
from app.services.seeder import seed_templates

STATIC_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    run_migrations()
    seed_templates()
    yield


app = FastAPI(title="Arrqitect", lifespan=lifespan)

app.include_router(templates.router)
app.include_router(apps.router)
app.include_router(jobs.router)
app.include_router(ws.router)

if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
