"""Static file server for the built admin single-page application."""

from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles


class AdminStaticFiles(StaticFiles):
    """Serve frontend assets and fall back to ``index.html`` for SPA routes."""

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


async def redirect_to_admin() -> RedirectResponse:
    """Redirect the application root to the built-in admin web UI."""

    return RedirectResponse(url="/admin/")
