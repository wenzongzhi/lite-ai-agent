import hashlib
import asyncio
import threading
import time
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from wechatpy.crypto import WeChatCrypto

from app import create_app
from cli.commands import CommandDispatcher
from tests.support import FakeDoubao
from wechat.router import SLOW_REPLY


def send_message(client, text, openid='user-openid-123456', msg_type='text'):
    crypto = client.app.state.services.crypto
    root = ET.Element('xml')
    for key, value in {'ToUserName': 'gh_test', 'FromUserName': openid, 'CreateTime': '1234567890',
                       'MsgType': msg_type, 'Content': text, 'MsgId': '123'}.items():
        ET.SubElement(root, key).text = value
    body = crypto.encrypt_message(ET.tostring(root, encoding='unicode'), 'test-nonce', '1234567890')
    params = {'msg_signature': ET.fromstring(body).findtext('MsgSignature'), 'timestamp': '1234567890', 'nonce': 'test-nonce'}
    response = client.post('/wechat', params=params, content=body)
    assert response.status_code == 200
    encrypted = ET.fromstring(response.content)
    decoded = crypto.decrypt_message(response.content, encrypted.findtext('MsgSignature'),
                                     encrypted.findtext('TimeStamp'), encrypted.findtext('Nonce'))
    return ET.fromstring(decoded).findtext('Content')


def test_get_verification_and_error_responses(settings_factory):
    with TestClient(create_app(settings_factory(), doubao=FakeDoubao())) as client:
        for path in ('/', '/wechat', '/docs', '/redoc', '/openapi.json'):
            response = client.get(path)
            assert response.status_code == 404 and response.text == 'Not Found'
        nonce, timestamp = 'nonce', '1234567890'
        signature = hashlib.sha1(''.join(sorted(('test-token-secret', timestamp, nonce))).encode()).hexdigest()
        assert client.get('/wechat', params={'signature': signature, 'nonce': nonce, 'timestamp': timestamp, 'echostr': 'challenge'}).text == 'challenge'
        assert client.get('/wechat', params={'signature': 'invalid', 'nonce': nonce, 'timestamp': timestamp, 'echostr': 'challenge'}).status_code == 404
        response = client.post('/wechat', content='invalid')
        assert response.status_code == 400 and response.text == 'Error'


def test_real_aes_text_and_nontext_reply(settings_factory):
    fake = FakeDoubao(answer='encrypted answer')
    with TestClient(create_app(settings_factory(), doubao=fake)) as client:
        assert send_message(client, 'hello') == 'encrypted answer'
        assert send_message(client, '结果') == 'encrypted answer'
        assert send_message(client, '', msg_type='event') == '当前测试版本只支持文字消息。'
        assert len(fake.simple_calls) == 1


def test_aes_slow_job_survives_callback_and_restart(settings_factory):
    settings = settings_factory(server={'fast_reply_timeout_seconds': 0.001})
    fake = FakeDoubao(answer='durable slow answer', delay=0.02)
    with TestClient(create_app(settings, doubao=fake)) as client:
        assert send_message(client, 'slow question') == SLOW_REPLY
        time.sleep(0.06)
        assert send_message(client, '结果') == 'durable slow answer'
    with TestClient(create_app(settings, doubao=FakeDoubao())) as client:
        assert send_message(client, '结果') == 'durable slow answer'


def test_bad_signature_and_invalid_app_id(settings_factory):
    with TestClient(create_app(settings_factory(), doubao=FakeDoubao())) as client:
        body = client.app.state.services.crypto.encrypt_message('<xml/>', 'n', '1')
        response = client.post('/wechat', content=body, params={'msg_signature': 'wrong', 'timestamp': '1', 'nonce': 'n'})
        assert response.status_code == 403 and response.text == 'Error'
        foreign_crypto = WeChatCrypto('test-token-secret', settings_factory().wechat.encoding_aes_key, 'wx_other')
        body = foreign_crypto.encrypt_message('<xml/>', 'n', '1')
        response = client.post('/wechat', content=body, params={'msg_signature': ET.fromstring(body).findtext('MsgSignature'),
                                                             'timestamp': '1', 'nonce': 'n'})
        assert response.status_code == 403 and response.text == 'Error'


def test_cli_controls_work_during_inflight_request(settings_factory):
    entered = threading.Event()
    class PendingDoubao(FakeDoubao):
        async def simple_answer(self, messages, model):
            entered.set()
            await asyncio.sleep(0.1)
            return 'in-flight answer'
    with TestClient(create_app(settings_factory(), doubao=PendingDoubao())) as client:
        answers = []
        worker = threading.Thread(target=lambda: answers.append(send_message(client, 'pending question')))
        worker.start()
        assert entered.wait(timeout=2)
        console = CommandDispatcher(client.app.state.services)
        assert 'active-jobs: 1' in console.execute('status')
        assert 'disabled' in console.execute('disable ai-answer')
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert answers == ['in-flight answer']
        assert send_message(client, 'new question') == 'AI回答功能当前已关闭。'
        assert send_message(client, '结果') == 'in-flight answer'
