import asyncio
import base64
from dataclasses import replace

import pytest

from config import DoubaoSettings, Settings, WeChatSettings, normalize_encoding_aes_key
from services import Services
from tests.support import FakeDoubao


@pytest.fixture
def settings_factory(tmp_path):
    def make(**sections):
        settings = Settings(
            wechat=WeChatSettings(token='test-token-secret', app_id='wx_test', app_secret='test-app-secret',
                encoding_aes_key=normalize_encoding_aes_key(base64.b64encode(b'k' * 32).decode().rstrip('='))),
            doubao=DoubaoSettings(api_key='test-doubao-secret', model='test-model'),
        )
        settings = replace(settings, database=replace(settings.database, path=str(tmp_path / 'agent.db')))
        return replace(settings, **{key: replace(getattr(settings, key), **values) for key, values in sections.items()})
    return make


@pytest.fixture
def services(settings_factory):
    container = Services(settings_factory(), doubao=FakeDoubao())
    yield container
    asyncio.run(container.close())
