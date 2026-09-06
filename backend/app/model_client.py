from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic

from .config import settings


class MissingModelKeyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "ANTHROPIC_API_KEY is not configured on the server. The service cannot call the "
            "model and will not fake a response."
        )


@dataclass
class ModelResponse:
    stop_reason: str
    content: list[dict[str, Any]]
    usage_input_tokens: int
    usage_output_tokens: int


class ModelClient:
    def __init__(self):
        if not settings.ANTHROPIC_API_KEY:
            raise MissingModelKeyError()
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def send(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
              max_tokens: int = 4096) -> ModelResponse:
        resp = self._client.messages.create(
            model=settings.MODEL, max_tokens=max_tokens, system=system, messages=messages, tools=tools,
        )
        return ModelResponse(
            stop_reason=resp.stop_reason,
            content=[b.model_dump() for b in resp.content],
            usage_input_tokens=resp.usage.input_tokens,
            usage_output_tokens=resp.usage.output_tokens,
        )
