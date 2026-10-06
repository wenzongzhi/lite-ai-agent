import asyncio
import inspect
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Callable

from agent.models import ToolCall
from tools.calculator import calculator
from tools.fortune import fortune_telling
from tools.memory_tool import memory_search

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    handler: Callable
    risk: str = "low"
    timeout: float | None = None
    enabled: Callable = lambda: True

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": self.parameters}}


def object_schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool: ToolDefinition):
        if tool.name in self._tools:
            raise ValueError("Duplicate tool registration")
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def schemas(self):
        return [tool.schema() for tool in self._tools.values() if tool.enabled()]


def validate_arguments(arguments: str, schema: dict) -> dict:
    """Validate the flat object schemas used by this registry, fail closed."""
    if len(arguments) > 16384:
        raise ValueError("Arguments are too large")
    try:
        values = json.loads(arguments, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise ValueError("Arguments must be valid JSON") from None
    if not isinstance(values, dict) or set(values) - set(schema['properties']) or set(schema['required']) - set(values):
        raise ValueError("Invalid argument fields")
    for key, value in values.items():
        rule = schema['properties'][key]
        valid = {"string": isinstance(value, str), "integer": type(value) is int,
                 "number": type(value) in (int, float), "boolean": type(value) is bool}.get(rule['type'], False)
        if not valid:
            raise ValueError("Invalid argument type")
        if isinstance(value, str) and not 1 <= len(value.strip()) <= rule.get('maxLength', 1000):
            raise ValueError("Invalid argument length")
        if 'enum' in rule and value not in rule['enum']:
            raise ValueError("Invalid argument option")
        if type(value) in (int, float) and (not math.isfinite(value) or value < rule.get('minimum', -1e100) or value > rule.get('maximum', 1e100)):
            raise ValueError("Invalid numeric argument")
    return values


class ToolDispatcher:
    def __init__(self, registry, state, repository):
        self.registry, self.state, self.repository = registry, state, repository

    async def execute(self, openid: str, call: ToolCall, *, confirmed: bool = False) -> dict:
        started = time.monotonic()
        result = {"ok": False, "error": "unknown_tool"}
        try:
            tool = self.registry.get(call.name)
            if tool is None:
                return result
            user = self.repository.get_user(openid)
            snapshot = self.state.snapshot()
            if not snapshot.features.ai_agent_enabled or not user or not user['agent_enabled'] or not tool.enabled():
                result = {"ok": False, "error": "tool_not_allowed"}
                return result
            if tool.risk != 'low' and not confirmed:
                result = {"ok": False, "error": "confirmation_required"}
                return result
            arguments = validate_arguments(call.arguments, tool.parameters)
            async def invoke():
                if inspect.iscoroutinefunction(tool.handler):
                    return await tool.handler(openid=openid, **arguments)
                return await asyncio.to_thread(tool.handler, openid=openid, **arguments)
            timeout = min(snapshot.agent.tool_timeout_seconds, tool.timeout or snapshot.agent.tool_timeout_seconds)
            value = await asyncio.wait_for(invoke(), timeout=timeout)
            result = {"ok": True, "result": value}
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > snapshot.agent.max_tool_result_bytes:
                result = {"ok": False, "error": "tool_result_too_large"}
        except asyncio.TimeoutError:
            result = {"ok": False, "error": "tool_timeout"}
        except (ValueError, TypeError, OverflowError):
            result = {"ok": False, "error": "invalid_arguments_or_result"}
        except Exception:
            result = {"ok": False, "error": "tool_failed"}
        finally:
            # Log only a registered name, never arbitrary model arguments or errors.
            name = call.name if self.registry.get(call.name) else '<unknown>'
            logger.info("Tool name=%s duration=%.3fs success=%s", name, time.monotonic() - started, result['ok'])
        return result


def build_registry(state, repository, web_provider=None):
    registry = ToolRegistry()
    registry.register(ToolDefinition("calculator", "Perform arithmetic calculations using numeric constants and + - * / % **.",
        object_schema({"expression": {"type": "string", "maxLength": 500}}, ["expression"]),
        lambda openid, expression: calculator(expression)))
    registry.register(ToolDefinition("memory_search", "Search the requesting user's curated older memories when recent context is insufficient.",
        object_schema({"query": {"type": "string", "maxLength": 500}}, ["query"]),
        lambda openid, query: memory_search(repository, openid, query),
        enabled=lambda: state.snapshot().agent.memory_search_enabled))
    registry.register(ToolDefinition("fortune_telling", "Entertainment-only simulated fortune telling; not factual prediction or professional advice.",
        object_schema({"topic": {"type": "string", "maxLength": 500}, "method": {"type": "string", "enum": ["tarot", "random"]}}, ["topic"]),
        lambda openid, topic, method="tarot": fortune_telling(topic, method)))
    if web_provider is not None:
        async def search(openid, query):
            return await web_provider.search(query, state.snapshot().web_search_max_results)
        registry.register(ToolDefinition("web_search", "Search the web and return compact titles, URLs, and snippets.",
            object_schema({"query": {"type": "string", "maxLength": 500}}, ["query"]), search,
            enabled=lambda: state.snapshot().web_search_enabled))
    return registry
