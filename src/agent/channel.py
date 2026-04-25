from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChannelMessage:
    user_id: str        # "wa:917845952289" | "app:uuid-here"
    channel: str        # "whatsapp" | "app" | "voice"
    text: str
    media_id: Optional[str] = None
    media_type: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class ChannelResponse:
    text: str
    intent: str
    role: str
    interactive_payload: Optional[dict] = None
