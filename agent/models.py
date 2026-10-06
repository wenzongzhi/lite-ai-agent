from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str

    def as_dict(self):
        return {"id": self.call_id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class ModelResponse:
    final_answer: FinalAnswer | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    content: str = ""

    def assistant_message(self):
        return {"role": "assistant", "content": self.content or None,
                "tool_calls": [call.as_dict() for call in self.tool_calls]}
