"""Shared pagination for bounded operations list queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from django.db.models import QuerySet

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    count: int


def paginate_queryset(
    queryset: QuerySet[T],
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Page[T]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    count = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    return Page(items=list(queryset[start:end]), page=page, page_size=page_size, count=count)
