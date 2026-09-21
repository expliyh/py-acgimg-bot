"""Static file server for the built admin single-page application."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles


class AdminStaticFiles(StaticFiles):
    """Serve frontend assets and fall back to ``index.html`` for SPA routes."""

    async def get_response(self, path: str, scope: dict) -> Response:
        normalized_path = path.replace("\\", "/").lstrip("/")
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            # Only extensionless URLs are client-side routes. Returning
            # index.html for a missing JS/CSS chunk makes browsers report a
            # misleading dynamic-import error after a frontend deployment.
            if Path(normalized_path).suffix or normalized_path.startswith("assets/"):
                raise
            response = await super().get_response("index.html", scope)

        if response.headers.get("content-type", "").startswith("text/html"):
            # The HTML points at the current hashed asset names and must be
            # revalidated after each deployment.
            response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
        elif normalized_path.startswith("assets/"):
            # Vite asset filenames contain content hashes, so they are safe to
            # retain indefinitely once the current index has been refreshed.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


async def redirect_to_admin() -> RedirectResponse:
    """Redirect the application root to the built-in admin web UI."""

    return RedirectResponse(url="/admin/")
