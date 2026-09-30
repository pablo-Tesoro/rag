"""Request and response models of the HTTP API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(
        default=None,
        pattern=THREAD_ID_PATTERN,
        description="Continue an existing conversation; omit to start a new one.",
    )


class ApprovalRequest(BaseModel):
    approved: bool


class Citation(BaseModel):
    documento: str
    seccion: str


class Answer(BaseModel):
    texto: str
    citas: list[Citation]
    sin_evidencia: bool
    terminacion: str
    citas_descartadas: list[Citation] = Field(default_factory=list)


class PendingAction(BaseModel):
    action: str
    args: dict[str, Any]
    operation: dict[str, Any]


class ChatResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "pending_approval", "failed"]
    answer: Answer | None = None
    pending_action: PendingAction | None = None
    prompt_version: str
    retrieval_mode: str
