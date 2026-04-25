from pydantic import BaseModel


class BaseToolResult(BaseModel):
    success: bool
    reply: str    # human-readable summary sent back to user
