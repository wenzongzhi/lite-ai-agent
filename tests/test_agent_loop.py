import asyncio
import json

from agent.models import FinalAnswer, ModelResponse, ToolCall
from tests.support import FakeDoubao


def test_single_tool_call_executes_exactly_once(services):
    async def scenario():
        services.repository.set_agent_enabled('a', True)
        services.runtime.doubao = FakeDoubao([
            ModelResponse(tool_calls=(ToolCall('one', 'calculator', '{"expression":"37*928"}'),)),
            ModelResponse(final_answer=FinalAnswer('34336')),
        ])
        assert await services.router.handle_text('a', 'Calculate 37*928') == '34336'
        rows = services.repository._rows("SELECT role FROM messages WHERE role='tool'")
        assert len(rows) == 1
    asyncio.run(scenario())


def test_native_tool_loop_multiple_calls_and_final_answer(services):
    async def scenario():
        services.repository.set_agent_enabled('a', True)
        fake = FakeDoubao([
            ModelResponse(tool_calls=(ToolCall('c1', 'calculator', '{"expression":"37 * 928"}'),)),
            ModelResponse(tool_calls=(ToolCall('c2', 'calculator', '{"expression":"1+2"}'),)),
            ModelResponse(final_answer=FinalAnswer('34336 and 3')),
        ])
        services.runtime.doubao = fake
        assert await services.router.handle_text('a', 'Please calculate') == '34336 and 3'
        assert len(fake.agent_calls) == 3
        history = fake.agent_calls[-1]['messages']
        tools = [msg for msg in history if msg['role'] == 'tool']
        assert [msg['tool_call_id'] for msg in tools] == ['c1', 'c2']
        assert json.loads(tools[0]['content'])['result']['result'] == 34336
        assert sum(row['role'] == 'tool' for row in services.repository._rows('SELECT role FROM messages')) == 2
        for index, msg in enumerate(history):
            if msg['role'] == 'tool':
                assert any(previous.get('tool_calls') and any(call['id'] == msg['tool_call_id'] for call in previous['tool_calls'])
                           for previous in history[:index])
    asyncio.run(scenario())


def test_unknown_tool_and_max_steps(services):
    async def scenario():
        services.repository.set_agent_enabled('a', True)
        fake = FakeDoubao([ModelResponse(tool_calls=(ToolCall(str(i), 'unknown', '{}'),)) for i in range(6)])
        services.runtime.doubao = fake
        assert await services.router.handle_text('a', 'loop') == '任务步骤过多，已停止继续执行。'
        assert len(fake.agent_calls) == 6
        result = fake.agent_calls[1]['messages'][-1]
        assert json.loads(result['content'])['error'] == 'unknown_tool'
    asyncio.run(scenario())


def test_recent_context_summary_and_memory_retrieval(services):
    async def scenario():
        repo = services.repository
        repo.set_agent_enabled('a', True)
        repo.add_message('a', 'user', 'I develop a WeChat agent')
        repo.add_message('a', 'assistant', 'Understood')
        repo.save_memory('a', 'summary', 'User develops a WeChat agent')
        repo.save_memory('a', 'decision', 'Older decision: use SQLite persistence')
        fake = FakeDoubao([ModelResponse(tool_calls=(ToolCall('m1', 'memory_search', '{"query":"SQLite"}'),)),
                           ModelResponse(final_answer=FinalAnswer('You chose SQLite'))])
        services.runtime.doubao = fake
        assert await services.router.handle_text('a', 'What did I choose?') == 'You chose SQLite'
        first = fake.agent_calls[0]['messages']
        assert sum(msg['content'] == 'What did I choose?' for msg in first) == 1
        assert any('User develops' in msg['content'] for msg in first)
        assert any(msg['content'] == 'Understood' for msg in first)
        assert 'SQLite' in fake.agent_calls[1]['messages'][-1]['content']
    asyncio.run(scenario())
