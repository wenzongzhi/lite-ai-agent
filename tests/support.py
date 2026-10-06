import asyncio

from agent.models import FinalAnswer, ModelResponse


class FakeDoubao:
    def __init__(self, responses=(), answer='mock answer', delay=0):
        self.responses = list(responses)
        self.answer, self.delay = answer, delay
        self.simple_calls, self.agent_calls = [], []

    async def simple_answer(self, messages, model):
        self.simple_calls.append({'messages': messages, 'model': model})
        await asyncio.sleep(self.delay)
        return self.answer

    async def chat_with_tools(self, messages, tool_schemas, model):
        import copy
        self.agent_calls.append({'messages': copy.deepcopy(messages), 'tools': tool_schemas, 'model': model})
        await asyncio.sleep(self.delay)
        return self.responses.pop(0) if self.responses else ModelResponse(final_answer=FinalAnswer(self.answer))
