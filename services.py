"""Construct one service graph per process; secrets stay in frozen startup settings."""

from dataclasses import replace

from agent.doubao import DoubaoClient
from agent.runtime import AgentRuntime
from agent.state import RuntimeState
from config import load_settings
from memory.db import Database
from memory.repository import Repository
from tools.registry import ToolDispatcher, build_registry
from tools.web_search import BraveSearchProvider
from wechat.crypto import create_crypto
from wechat.router import MessageRouter


class Services:
    def __init__(self, settings, doubao=None):
        self.settings = settings
        self.state = RuntimeState(settings)
        self.crypto = create_crypto(settings.wechat)
        self.database = Database(settings.database.path)
        self.repository = Repository(self.database)
        self.repository.recover_interrupted_jobs()
        self.web_provider = (BraveSearchProvider(settings.web_search.api_key)
            if settings.web_search.api_key and settings.web_search.provider == 'brave' else None)
        self.registry = build_registry(self.state, self.repository, self.web_provider)
        self.dispatcher = ToolDispatcher(self.registry, self.state, self.repository)
        self.doubao = doubao or DoubaoClient(settings.doubao)
        self.runtime = AgentRuntime(self.doubao, self.state, self.repository, self.registry, self.dispatcher)
        self.router = MessageRouter(self.state, self.repository, self.runtime)

    def reload_config(self):
        updated = load_settings()
        restart_fields = []
        for name, changed in (
            ('wechat', updated.wechat != self.settings.wechat),
            ('doubao connection', replace(updated.doubao, model=self.settings.doubao.model) != self.settings.doubao),
            ('server listener', (updated.server.host, updated.server.port) != (self.settings.server.host, self.settings.server.port)),
            ('database', updated.database != self.settings.database),
            ('web_search credentials/provider', (updated.web_search.api_key, updated.web_search.provider) !=
             (self.settings.web_search.api_key, self.settings.web_search.provider)),
            ('calendar', updated.calendar != self.settings.calendar),
        ):
            if changed:
                restart_fields.append(name)
        # A newly supplied secret needs a restart before its provider is available.
        effective = replace(updated, web_search=replace(updated.web_search,
                            enabled=updated.web_search.enabled and self.web_provider is not None))
        self.state.reload(effective)
        return restart_fields

    async def close(self):
        await self.router.shutdown()
        self.database.close()
