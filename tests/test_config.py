import base64
import pytest

from config import ConfigError, load_settings


def credentials():
    return {'WECHAT_TOKEN': 'secret-token', 'WECHAT_ENCODING_AES_KEY': base64.b64encode(b'a' * 32).decode().rstrip('='),
            'WECHAT_APP_ID': 'wx_test', 'WECHAT_APP_SECRET': 'secret-app', 'DOUBAO_API_KEY': 'secret-api', 'DOUBAO_MODEL': 'model-test'}


def test_toml_and_environment_precedence(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[doubao]\nmodel = "toml-model"\n[server]\nfast_reply_timeout_seconds = 2.5\n', encoding='utf-8')
    settings = load_settings(environ={**credentials(), 'WECHAT_AGENT_CONFIG': str(path), 'FAST_REPLY_TIMEOUT_SECONDS': '1.25'})
    assert settings.doubao.model == 'model-test'
    assert settings.server.fast_reply_timeout_seconds == 1.25
    assert len(settings.wechat.encoding_aes_key) == 44
    env = credentials()
    del env['DOUBAO_MODEL']
    assert load_settings(path, environ=env).doubao.model == 'toml-model'


def test_missing_secrets_and_repr_are_safe(tmp_path):
    path = tmp_path / 'empty.toml'
    path.write_text('')
    with pytest.raises(ConfigError, match='wechat.token'):
        load_settings(path, environ={})
    settings = load_settings(path, environ=credentials())
    for key in ('WECHAT_TOKEN', 'WECHAT_APP_SECRET', 'DOUBAO_API_KEY', 'WECHAT_ENCODING_AES_KEY'):
        assert credentials()[key] not in repr(settings)


@pytest.mark.parametrize('field,value', [('FAST_REPLY_TIMEOUT_SECONDS', '0'), ('FAST_REPLY_TIMEOUT_SECONDS', 'nan'),
    ('FAST_REPLY_TIMEOUT_SECONDS', '-1'), ('AGENT_MAX_STEPS', '0'), ('AGENT_TOOL_TIMEOUT_SECONDS', '0'),
    ('FEATURES_AI_ANSWER_ENABLED', 'invalid')])
def test_invalid_config(tmp_path, field, value):
    path = tmp_path / 'empty.toml'
    path.write_text('')
    with pytest.raises(ConfigError):
        load_settings(path, environ={**credentials(), field: value})


def test_invalid_aes_and_toml_never_echo_secrets(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('')
    with pytest.raises(ConfigError) as error:
        load_settings(path, environ={**credentials(), 'WECHAT_ENCODING_AES_KEY': 'top-secret-invalid-key'})
    assert 'top-secret-invalid-key' not in str(error.value)
    path.write_text('[doubao]\napi_key = "SECRET INVALID TOML', encoding='utf-8')
    with pytest.raises(ConfigError) as error:
        load_settings(path, environ=credentials())
    assert 'SECRET INVALID TOML' not in str(error.value)


def test_malformed_url_and_unknown_settings(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('')
    with pytest.raises(ConfigError, match='doubao.base_url'):
        load_settings(path, environ={**credentials(), 'DOUBAO_BASE_URL': 'https://[secret-invalid-url'})
    path.write_text('[agent]\nmax_step = 2\n')
    with pytest.raises(ConfigError, match='Unknown configuration field'):
        load_settings(path, environ=credentials())
