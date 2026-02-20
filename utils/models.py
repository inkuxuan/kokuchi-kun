from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AuthResult:
    success: bool
    error: str | None = None
    user_id: str | None = None
    display_name: str | None = None
    method: str | None = None
    reauthenticated: bool = False


@dataclass
class ApiResult:
    success: bool
    error: str | None = None
    data: dict[str, Any] | None = None


@dataclass
class AIProcessingResult:
    success: bool
    error: str | None = None
    timestamp: int | None = None
    announcement_timestamp: int | None = None
    event_start_timestamp: int | None = None
    event_end_timestamp: int | None = None
    formatted_date_time: str | None = None
    title: str | None = None
    event_title: str | None = None
    content: str | None = None


@dataclass
class JobData:
    id: str
    message_id: str
    timestamp: float
    title: str
    content: str
    status: str = "pending"
    event_start_timestamp: float | None = None
    event_end_timestamp: float | None = None
    event_title: str | None = None
    formatted_date_time: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "JobData":
        return cls(
            id=d["id"],
            message_id=d["message_id"],
            timestamp=d["timestamp"],
            title=d["title"],
            content=d["content"],
            status=d.get("status", "pending"),
            event_start_timestamp=d.get("event_start_timestamp"),
            event_end_timestamp=d.get("event_end_timestamp"),
            event_title=d.get("event_title"),
            formatted_date_time=d.get("formatted_date_time"),
        )
