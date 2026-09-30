"""Typed graph state and per-invocation context.

State is what the checkpointer persists per conversation thread. Context is what each
invocation brings from outside and is *not* persisted: the employee identity comes from
the request, every time, never from the model or from stored state.
"""

from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from bank_assistant.identity import Employee
from bank_assistant.retrieval import RetrievalMode


class RetrievedRef(TypedDict):
    doc_id: str
    section: str
    title: str
    status: str


def merge_retrieved(
    left: dict[str, RetrievedRef] | None, right: dict[str, RetrievedRef] | None
) -> dict[str, RetrievedRef]:
    """Chunks seen in the thread, by chunk id. Citations are checked against them."""
    return {**(left or {}), **(right or {})}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Owner of the thread: the API refuses to continue a thread for anybody else.
    employee_id: str
    retrieved: Annotated[dict[str, RetrievedRef], merge_retrieved]
    # Structured answer of the current turn; the API resets it to None on each new turn.
    final_answer: dict[str, Any] | None


@dataclass(frozen=True)
class AgentContext:
    employee: Employee
    retrieval_mode: RetrievalMode
