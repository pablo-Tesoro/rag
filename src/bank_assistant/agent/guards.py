"""Pure helpers that keep the agent loop bounded and honest.

All of them are derived from the message history of the current turn (everything after
the last human message), so no extra counters need to live in the state.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall, ToolMessage

from bank_assistant.agent.schemas import ANSWER_TOOL, Cita
from bank_assistant.agent.state import RetrievedRef


def current_turn(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return list(messages[index + 1 :])
    return list(messages)


def tool_calls_in_turn(messages: Sequence[AnyMessage]) -> list[ToolCall]:
    return [
        call
        for message in current_turn(messages)
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


def call_signature(name: str, args: Mapping[str, Any]) -> str:
    """Canonical form of a call: same tool + same arguments, whatever the key order."""
    return name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)


def working_calls_in_turn(messages: Sequence[AnyMessage]) -> int:
    """Tool calls made in this turn, excluding the final `responder` call."""
    return sum(1 for call in tool_calls_in_turn(messages) if call["name"] != ANSWER_TOOL)


def answer_corrections_in_turn(messages: Sequence[AnyMessage]) -> int:
    """How many times this turn the final answer was sent back to the model for fixing."""
    return sum(
        1
        for message in current_turn(messages)
        if isinstance(message, ToolMessage)
        and message.name == ANSWER_TOOL
        and message.status == "error"
    )


def citation_is_supported(cita: Cita, retrieved: Mapping[str, RetrievedRef]) -> bool:
    """A citation is valid if the cited section (or a subsection/parent of it) was retrieved.

    Parents count too: a chunk of section "3.1" supports citing "3", and vice versa.
    """
    for ref in retrieved.values():
        if ref["doc_id"] != cita.documento:
            continue
        cited, seen = cita.seccion, ref["section"]
        if cited == seen or seen.startswith(cited + ".") or cited.startswith(seen + "."):
            return True
    return False
