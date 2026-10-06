"""Native Ark Chat Completions adapter; vendor JSON stops at this boundary."""

import logging
import time

import httpx

from agent.models import FinalAnswer, ModelResponse, ToolCall
from config import DoubaoSettings

logger = logging.getLogger(__name__)


class DoubaoError(RuntimeError):
    pass


def normalize_response(data: dict) -> ModelResponse:
    try:
        message = data['choices'][0]['message']
        content = message.get('content') or ""
        if not isinstance(content, str):
            raise ValueError()
        raw_calls = message.get('tool_calls') or []
        if not isinstance(raw_calls, list) or len(raw_calls) > 8:
            raise ValueError()
        calls = []
        for call in raw_calls:
            function = call['function']
            call_id, name, arguments = call['id'], function['name'], function['arguments']
            if call.get('type') != 'function' or not all(isinstance(x, str) and x for x in (call_id, name, arguments)):
                raise ValueError()
            if len(arguments) > 16384 or len(name) > 100 or len(call_id) > 200:
                raise ValueError()
            calls.append(ToolCall(call_id, name, arguments))
        if len({call.call_id for call in calls}) != len(calls):
            raise ValueError()
        if calls:
            return ModelResponse(tool_calls=tuple(calls), content=content.strip())
        if content.strip():
            return ModelResponse(final_answer=FinalAnswer(content.strip()))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    raise DoubaoError("Doubao returned an invalid or empty response")


class DoubaoClient:
    def __init__(self, settings: DoubaoSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client

    async def _post(self, payload):
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        started = time.monotonic()
        try:
            if self.client is not None:
                response = await self.client.post(self.settings.base_url, headers=headers, json=payload,
                                                  timeout=self.settings.http_timeout_seconds)
            else:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                    response = await client.post(self.settings.base_url, headers=headers, json=payload)
            response.raise_for_status()
            return normalize_response(response.json())
        except (httpx.HTTPError, ValueError):
            # Neither vendor bodies nor exception text are safe to log or persist.
            raise DoubaoError("Doubao request failed") from None
        finally:
            logger.info("Doubao request duration=%.3fs", time.monotonic() - started)

    async def simple_answer(self, messages, model: str) -> str:
        response = await self._post({"model": model, "messages": messages, "stream": False, "max_tokens": 1000})
        if response.tool_calls or not response.final_answer:
            raise DoubaoError("Unexpected tool call in simple-answer mode")
        return response.final_answer.text

    async def chat_with_tools(self, messages, tool_schemas, model: str) -> ModelResponse:
        payload = {"model": model, "messages": messages, "stream": False, "max_tokens": 1000}
        if tool_schemas:
            payload.update(tools=tool_schemas, tool_choice="auto")
        return await self._post(payload)
