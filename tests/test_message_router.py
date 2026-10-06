import asyncio

from wechat.router import BUSY_REPLY, SLOW_REPLY


def test_user_gating_and_result_after_global_disable(services):
    async def scenario():
        router, repo, state = services.router, services.repository, services.state
        assert await router.handle_text('a', 'hello') == 'mock answer'
        assert len(services.doubao.simple_calls) == 1
        assert not services.doubao.agent_calls
        assert await router.handle_text('a', '开启豆包agent功能') == '豆包Agent功能已开启。'
        assert repo.get_user('a')['agent_enabled'] == 1
        assert await router.handle_text('a', 'agent question') == 'mock answer'
        assert len(services.doubao.agent_calls) == 1
        state.set_feature('ai-agent', False)
        assert await router.handle_text('a', 'new question') == 'Agent功能当前已关闭。'
        assert repo.get_user('a')['agent_enabled'] == 1
        assert await router.handle_text('a', '结果') == 'mock answer'
        assert await router.handle_text('a', '关闭豆包agent功能') == '豆包Agent功能已关闭。'
        state.set_feature('ai-answer', False)
        assert await router.handle_text('a', 'new question') == 'AI回答功能当前已关闭。'
        assert await router.handle_text('a', '结果') == 'mock answer'
        assert len(services.doubao.simple_calls) == 1 and len(services.doubao.agent_calls) == 1
    asyncio.run(scenario())


def test_slow_jobs_shield_concurrency_and_retrieval(services):
    async def scenario():
        services.doubao.delay = 0.04
        services.state.set_fast_timeout(0.001)
        router = services.router
        assert await router.handle_text('a', 'slow question') == SLOW_REPLY
        assert await router.handle_text('a', '结果') == '任务仍在处理中，请稍后再试。'
        assert await router.handle_text('a', 'second question') == BUSY_REPLY
        assert await router.handle_text('b', 'different user') == SLOW_REPLY
        assert services.repository.active_job_count() == 2
        services.state.set_feature('ai-answer', False)
        await asyncio.gather(*list(router.active_tasks.values()))
        assert await router.handle_text('a', '结果') == 'mock answer'
        assert services.repository.latest_job('b')['status'] == 'done'
        assert len(services.doubao.simple_calls) == 2
    asyncio.run(scenario())


def test_whitelist_mode_and_agent_slow_job(services, settings_factory):
    async def scenario():
        services.state.reload(settings_factory(features={'allow_user_agent_self_enable': False}))
        assert await services.router.handle_text('a', '开启豆包agent功能') == '请联系管理员开启Agent功能。'
        assert not services.repository.get_user('a')['agent_enabled']
        services.repository.set_agent_enabled('a', True)
        services.doubao.delay = 0.02
        services.state.set_fast_timeout(0.001)
        assert await services.router.handle_text('a', 'agent question') == SLOW_REPLY
        await asyncio.gather(*list(services.router.active_tasks.values()))
        assert await services.router.handle_text('a', '结果') == 'mock answer'
        assert not services.doubao.simple_calls
    asyncio.run(scenario())


def test_restart_interruption_and_failure_dont_leak(services):
    async def scenario():
        repo = services.repository
        repo.ensure_user('a')
        job = repo.create_job('a', 'ai-answer', 'interrupted')
        repo.recover_interrupted_jobs()
        assert await services.router.handle_text('a', '结果') == '上一次任务因程序重启而中断，请重新发送问题。'
        async def fail(*args, **kwargs):
            raise RuntimeError('secret Authorization: Bearer leaked')
        services.runtime.run_simple_answer = fail
        assert '异常' in await services.router.handle_text('a', 'failing question')
        assert repo.latest_job('a')['error'] == 'ai_request_failed'
        assert 'secret' not in repo.latest_job('a')['error']
    asyncio.run(scenario())
