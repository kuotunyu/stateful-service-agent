from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Proposal(BaseModel):
    """Untrusted model output. Identity and confirmation are deliberately absent."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["create", "reschedule", "cancel"]
    service: Literal["冷氣維修", "洗衣機維修"] | None = None
    slot: str | None = Field(default=None, max_length=40)
    booking_id: str | None = Field(default=None, max_length=80)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
