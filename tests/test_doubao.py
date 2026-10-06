import asyncio
import json

import httpx
import pytest

from agent.doubao import DoubaoClient, DoubaoError, normalize_response
from tools.web_search import BraveSearchProvider


def test_simple_request_has_no_tools_and_native_calls_normalize(settings_factory):
    async def scenario():
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(200, json={'choices': [{'message': {'content': ' ordinary answer '}}]})
            return httpx.Response(200, json={'choices': [{'message': {'content': None, 'tool_calls': [
                {'id': 'call1', 'type': 'function', 'function': {'name': 'calculator', 'arguments': '{"expression":"1+1"}'}}]}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            doubao = DoubaoClient(settings_factory().doubao, client=http)
            assert await doubao.simple_answer([{'role': 'user', 'content': 'hello'}], 'model') == 'ordinary answer'
            assert 'tools' not in requests[0] and 'tool_choice' not in requests[0]
            response = await doubao.chat_with_tools([], [{'type': 'function'}], 'model')
            assert response.tool_calls[0].call_id == 'call1'
            assert requests[1]['tool_choice'] == 'auto'
    asyncio.run(scenario())


def test_vendor_error_does_not_leak_secrets(settings_factory):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={'error': 'secret vendor body'}))) as http:
            with pytest.raises(DoubaoError) as error:
                await DoubaoClient(settings_factory().doubao, client=http).simple_answer([], 'model')
            assert 'secret' not in str(error.value)
    asyncio.run(scenario())
    for data in ({}, {'choices': []}, {'choices': [{'message': {'content': ''}}]}, {'choices': [{'message': {'content': 123}}]}):
        with pytest.raises(DoubaoError):
            normalize_response(data)


def test_brave_provider_compact_response_and_parameters():
    async def scenario():
        def handler(request):
            assert request.headers['X-Subscription-Token'] == 'brave-test-secret'
            assert request.url.params['q'] == 'WeChat'
            assert request.url.params['count'] == '2'
            return httpx.Response(200, json={'web': {'results': [
                {'title': 'Title', 'url': 'https://example.com', 'description': 'Snippet', 'extra': 'unused'}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await BraveSearchProvider('brave-test-secret', client=http).search('WeChat', 2)
            assert result == {'results': [{'title': 'Title', 'url': 'https://example.com', 'snippet': 'Snippet'}]}
    asyncio.run(scenario())
