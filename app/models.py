from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class Track:
    title: str
    webpage_url: str
    source: str = "YouTube"
    video_id: str = ""
    description: str = ""
    thumbnail_url: str = ""
    uploader: str = ""
    duration_seconds: int | None = None
    played: bool = False
    karaoke_artist: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Track":
        allowed = {field for field in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in data.items() if key in allowed})

    @property
    def duration_text(self) -> str:
        if not self.duration_seconds:
            return ""
        minutes, seconds = divmod(int(self.duration_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
