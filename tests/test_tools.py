import asyncio
import pytest

from agent.models import ToolCall
from tools.calculator import calculator
from tools.calendar import DisabledCalendarProvider
from tools.registry import ToolDefinition, object_schema
from tools.registry import build_registry


@pytest.mark.parametrize('expression,result', [('37 * 928', 34336), ('(1 + 2) ** 3', 27), ('-3 + +2', -1), ('7 % 4', 3)])
def test_calculator(expression, result):
    assert calculator(expression)['result'] == result


@pytest.mark.parametrize('expression', ['__import__("os").system("echo bad")', 'open("file")', 'x.__class__',
    '[x for x in range(10)]', '"abc"', 'True + 1', '9 ** 9999999', '1 / 0', '1e999', '(1+2j)', '1 << 3'])
def test_calculator_rejects_unsafe_input(expression):
    with pytest.raises(ValueError):
        calculator(expression)


def test_tool_dispatch_authorization_validation_and_tools(services):
    async def scenario():
        dispatcher, repo = services.dispatcher, services.repository
        repo.ensure_user('a')
        call = ToolCall('1', 'calculator', '{"expression":"37 * 928"}')
        assert (await dispatcher.execute('a', call))['error'] == 'tool_not_allowed'
        repo.set_agent_enabled('a', True)
        assert (await dispatcher.execute('a', call))['result']['result'] == 34336
        assert (await dispatcher.execute('a', ToolCall('2', 'shell', '{}')))['error'] == 'unknown_tool'
        for args in ('{"expression":1}', '{"expression":"1+1","openid":"b"}', '{bad', '[]', '{"expression":""}'):
            assert not (await dispatcher.execute('a', ToolCall('3', 'calculator', args)))['ok']
        repo.save_memory('a', 'project', 'WeChat project uses SQLite')
        repo.save_memory('b', 'project', 'Private SQLite project for b')
        result = await dispatcher.execute('a', ToolCall('4', 'memory_search', '{"query":"SQLite"}'))
        assert len(result['result']['matches']) == 1
        fortune = await dispatcher.execute('a', ToolCall('5', 'fortune_telling', '{"topic":"coding"}'))
        assert fortune['result']['entertainment_only'] is True
        services.state.set_feature('ai-agent', False)
        assert (await dispatcher.execute('a', call))['error'] == 'tool_not_allowed'
    asyncio.run(scenario())


def test_tool_timeout_result_limit_and_confirmation(services):
    async def slow(openid):
        await asyncio.sleep(1)
    async def scenario():
        services.repository.set_agent_enabled('a', True)
        registry = services.registry
        registry.register(ToolDefinition('slow', 'slow', object_schema({}, []), slow, timeout=0.001))
        assert (await services.dispatcher.execute('a', ToolCall('1', 'slow', '{}')))['error'] == 'tool_timeout'
        registry.register(ToolDefinition('large', 'large', object_schema({}, []), lambda openid: 'x' * 10000))
        assert (await services.dispatcher.execute('a', ToolCall('2', 'large', '{}')))['error'] == 'tool_result_too_large'
        executed = []
        registry.register(ToolDefinition('write', 'write', object_schema({}, []), lambda openid: executed.append(True), risk='write'))
        assert (await services.dispatcher.execute('a', ToolCall('3', 'write', '{}')))['error'] == 'confirmation_required'
        assert not executed
        assert (await DisabledCalendarProvider().create_event('title', 'start', 'end'))['error'] == 'confirmation_required'
    asyncio.run(scenario())


def test_disabled_optional_schemas_and_search_toggle(services, settings_factory):
    class Provider:
        async def search(self, query, max_results):
            return {'results': []}
    def names(registry):
        return {schema['function']['name'] for schema in registry.schemas()}
    assert 'web_search' not in names(services.registry)
    registry = build_registry(services.state, services.repository, Provider())
    assert 'web_search' not in names(registry)
    services.state.reload(settings_factory(web_search={'enabled': True, 'api_key': 'mock-key'},
        agent={'memory_search_enabled': False}))
    assert 'web_search' in names(registry)
    assert 'memory_search' not in names(registry)
    assert not any(name.startswith('calendar') for name in names(registry))


def test_memory_results_remain_small_for_long_chinese_records(services):
    async def scenario():
        services.repository.set_agent_enabled('a', True)
        for index in range(5):
            services.repository.save_memory('a', 'project', f'项目{index} ' + '测试中文记忆' * 250)
        result = await services.dispatcher.execute('a', ToolCall('mem', 'memory_search', '{"query":"测试"}'))
        assert result['ok']
        assert len(result['result']['matches']) == 5
        assert all(match['truncated'] for match in result['result']['matches'])
    asyncio.run(scenario())
