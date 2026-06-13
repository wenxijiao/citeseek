"""FastAPI application factory. Serves the built frontend in production."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..config import PROJECT_ROOT
from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="CiteSeek", version="0.1.0")
    # Dev convenience; the Vite proxy avoids CORS entirely in practice.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

        # Hashed assets may cache forever, but index.html must always be
        # revalidated or browsers keep loading stale bundles after rebuilds.
        @app.middleware("http")
        async def no_cache_index(request, call_next):
            response = await call_next(request)
            if not request.url.path.startswith(("/api", "/assets")):
                response.headers["Cache-Control"] = "no-cache"
            return response

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("citeseek.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
