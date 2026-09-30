"""Chat model factory: the provider is chosen by configuration, not by code.

`LLM_MODEL=google_genai:gemini-3.5-flash-lite` today; `anthropic:...` or `openai:...` would
work the same way once their integration package is installed. Timeouts and retries are
set here so no call can hang forever.
"""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


def build_chat_model(
    model: str,
    *,
    timeout_s: float,
    max_retries: int,
    temperature: float | None = None,
) -> BaseChatModel:
    kwargs: dict[str, Any] = {"timeout": timeout_s, "max_retries": max_retries}
    if temperature is not None:
        kwargs["temperature"] = temperature
    chat_model = init_chat_model(model, **kwargs)
    if not isinstance(chat_model, BaseChatModel):  # a "configurable" model is not expected here
        raise TypeError(f"{model!r} did not resolve to a chat model")
    return chat_model
