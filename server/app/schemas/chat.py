"""DTO cho public chat API `/api/chat` (spec §"Hợp đồng API", schema `chat.api/1`).

`machine_id` là lookup mutable (không hash); `machine_ref` bất biến chỉ tồn tại ở
`chat_turns`/audit details, không expose qua DTO.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class ConversationOut(BaseModel):
    """`chat.api/1` — hội thoại không kèm messages."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    machine_id: uuid.UUID | None = None
    message_count: int = 0
    last_message_at: datetime | None = None
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    """1 tin nhắn trong hội thoại."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    turn_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None
    error_category: str | None = None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    """Hội thoại + lịch sử messages + turn đang active (nếu có)."""

    messages: list[MessageOut] = Field(default_factory=list)
    active_turn_id: uuid.UUID | None = None


class ConversationListOut(BaseModel):
    items: list[ConversationOut] = Field(default_factory=list)
    total: int = 0


class ConversationCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    machine_id: uuid.UUID | None = None


class ConversationPatchIn(BaseModel):
    """PATCH: phân biệt 'không gửi' vs 'gửi null' qua `model_fields_set`."""

    title: str | None = Field(default=None, max_length=200)
    machine_id: uuid.UUID | None = None


class MachineContextIn(BaseModel):
    """Ngữ cảnh máy per-turn (override mềm, không đổi machine_id đã lưu)."""

    machine_id: uuid.UUID | None = None
    client_id: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=255)


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=settings.chat_max_message_chars)
    machine_context: MachineContextIn | None = None


class CancelIn(BaseModel):
    turn_id: uuid.UUID


class CancelOut(BaseModel):
    status: str
