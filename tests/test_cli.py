import threading
from dataclasses import replace

from cli.commands import CommandDispatcher, parse_command
from cli.repl import Console


def test_commands_and_secret_free_status(services):
    stopped = threading.Event()
    commands = CommandDispatcher(services, stopped.set)
    for feature in ('ai-answer', 'ai-agent'):
        assert 'disabled' in commands.execute(f'disable {feature}')
        assert 'enabled' in commands.execute(f'enable {feature}')
    assert commands.execute('set model cli-model') == 'model updated'
    assert commands.execute('show model') == 'cli-model'
    assert commands.execute('set fast-timeout 3.0') == 'fast-timeout updated'
    assert commands.execute('show fast-timeout') == '3s'
    assert commands.execute('set fast-timeout nan').startswith('Error:')
    assert commands.execute('set fast-timeout 0').startswith('Error:')
    assert commands.execute('set fast-timeout secret-value').startswith('Error:')
    assert 'secret-value' not in commands.execute('set fast-timeout secret-value')
    assert commands.execute('user agent enable openid-user-123456') == 'User agent: enabled'
    assert services.repository.get_user('openid-user-123456')['agent_enabled']
    assert 'openid-user-123456' not in commands.execute('users')
    assert 'openid-user-123456' not in commands.execute('user show openid-user-123456')
    assert commands.execute('user agent disable openid-user-123456') == 'User agent: disabled'
    assert commands.execute('memory save a project My project uses SQLite') == 'Memory saved'
    assert 'SQLite' in commands.execute('memory search a SQLite')
    assert 'memories' in commands.execute('memory stats')
    status = commands.execute('status')
    for secret in ('test-token-secret', 'test-app-secret', 'test-doubao-secret', services.settings.wechat.encoding_aes_key):
        assert secret not in status
    assert 'active-jobs: 0' in status
    assert commands.execute('quit') == 'Stopping server'
    assert stopped.is_set()


def test_reload_mutable_controls_and_report_restart(services, monkeypatch):
    updated = replace(services.settings, features=replace(services.settings.features, ai_answer_enabled=False),
        doubao=replace(services.settings.doubao, model='reloaded-model', api_key='new-secret'))
    monkeypatch.setattr('services.load_settings', lambda: updated)
    reply = CommandDispatcher(services).execute('config reload')
    assert 'restart required' in reply and 'new-secret' not in reply
    assert services.state.snapshot().doubao_model == 'reloaded-model'
    assert not services.state.snapshot().features.ai_answer_enabled
    assert services.doubao is not None
    assert services.settings.doubao.api_key == 'test-doubao-secret'


def test_console_thread_and_noninteractive_start(services):
    lines = iter(['disable ai-answer', 'set model from-console', 'quit'])
    output = []
    stopped = threading.Event()
    console = Console(CommandDispatcher(services, stopped.set), input_fn=lambda prompt: next(lines), output_fn=output.append)
    assert not console.start(interactive=False)
    assert console.thread is None
    assert console.start(interactive=True)
    console.thread.join(timeout=2)
    assert not console.thread.is_alive()
    assert stopped.is_set()
    assert services.state.snapshot().doubao_model == 'from-console'
    assert not services.state.snapshot().features.ai_answer_enabled
    assert parse_command('memory search a "two words"') == ['memory', 'search', 'a', 'two words']
