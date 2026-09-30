"""
HTTP hardening + serving the built frontend (launch Phase 9).

  - security headers on every response
  - request size limit (uploads: MAX_UPLOAD_MB, default 30)
  - the React app (frontend/dist) is served by the backend: a browser page load (GET that
    accepts text/html) of any app path gets index.html; API calls (JSON) go to the API.
    API and screens share paths like /shipments/58 — the Accept header tells them apart.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

DIST = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist"))
MAX_BODY = int(os.getenv("MAX_UPLOAD_MB", "30")) * 1024 * 1024


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class BodyLimit(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        size = request.headers.get("content-length")
        if size and size.isdigit() and int(size) > MAX_BODY:
            return JSONResponse(status_code=413, content={"detail": f"File is larger than {MAX_BODY // 1048576} MB"})
        return await call_next(request)


class SpaFallback(BaseHTTPMiddleware):
    """Page loads get the React app; everything else goes on to the API."""

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET" and DIST.is_dir():
            path = request.url.path
            asset = (DIST / path.lstrip("/")).resolve()
            if path != "/" and asset.is_file() and DIST.resolve() in asset.parents:
                return FileResponse(asset, headers={"Cache-Control": "public, max-age=31536000, immutable"}
                                    if "/assets/" in path else None)
            wants_page = "text/html" in request.headers.get("accept", "")
            if wants_page and not path.startswith(("/docs", "/redoc", "/openapi.json", "/oauth/")):
                return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
        return await call_next(request)


def cors_origins() -> list[str]:
    """Production: only the site itself. Development: the Vite dev server."""
    public = os.getenv("PUBLIC_URL", "").rstrip("/")
    if public:
        return [public]
    return ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]


def install(app: FastAPI) -> None:
    app.add_middleware(SpaFallback)
    app.add_middleware(BodyLimit)
    app.add_middleware(SecurityHeaders)
