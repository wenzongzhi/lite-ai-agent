"""Calendar integration boundary; OAuth and real writes are deferred."""

from typing import Protocol


class CalendarProvider(Protocol):
    async def list_events(self, start: str, end: str) -> dict: ...
    async def create_event(self, title: str, start: str, end: str, *, confirmed: bool) -> dict: ...


class DisabledCalendarProvider:
    async def list_events(self, start: str, end: str) -> dict:
        return {"error": "calendar_not_configured"}

    async def create_event(self, title: str, start: str, end: str, *, confirmed: bool = False) -> dict:
        return {"error": "confirmation_required" if not confirmed else "calendar_not_configured"}
