"""Shared response and pagination contracts for the admin API."""

from __future__ import annotations

from math import ceil
from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: dict[str, list[str]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


def page_meta(total: int, page: int, page_size: int) -> PageMeta:
    return PageMeta(
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )


def page_offset(page: int, page_size: int) -> int:
    return (page - 1) * page_size


def error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        502: "upstream_error",
        503: "service_unavailable",
    }.get(status_code, "internal_error")


def error_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "请求参数校验失败"
    return "请求处理失败"
