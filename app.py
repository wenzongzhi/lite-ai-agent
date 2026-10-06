"""FastAPI / WeChat AES adapter and the local server entry point."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from wechatpy import parse_message
from wechatpy.exceptions import InvalidAppIdException, InvalidSignatureException
from wechatpy.utils import check_signature

from cli.commands import CommandDispatcher
from cli.repl import Console
from config import ConfigError, load_settings
from services import Services
from wechat.crypto import build_encrypted_reply, mask_openid

logger = logging.getLogger(__name__)


def create_app(settings=None, *, doubao=None, interactive_cli=False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        services = Services(settings or load_settings(), doubao=doubao)
        application.state.services = services
        console = None
        try:
            if interactive_cli:
                console = Console(CommandDispatcher(services, application.state.shutdown))
                console.start()
            yield
        finally:
            if console:
                console.stop()
            await services.close()

    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    application.state.shutdown = lambda: None

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return PlainTextResponse("Not Found" if exc.status_code == 404 else "Error", status_code=exc.status_code)

    @application.get('/')
    async def root():
        return PlainTextResponse('Not Found', status_code=404)

    @application.get('/wechat', response_class=PlainTextResponse)
    async def wechat_get(request: Request, signature: str | None = None, timestamp: str | None = None,
                         nonce: str | None = None, echostr: str | None = None):
        # Preserve the working verification flow and plain 404 responses.
        if not all((signature, timestamp, nonce, echostr)):
            return PlainTextResponse('Not Found', status_code=404)
        try:
            check_signature(request.app.state.services.settings.wechat.token, signature, timestamp, nonce)
        except InvalidSignatureException:
            logger.warning('Invalid WeChat GET signature')
            return PlainTextResponse('Not Found', status_code=404)
        return PlainTextResponse(echostr)

    @application.post('/wechat')
    async def wechat_post(request: Request):
        started = time.monotonic()
        services = request.app.state.services
        msg_signature = request.query_params.get('msg_signature')
        timestamp = request.query_params.get('timestamp')
        nonce = request.query_params.get('nonce')
        if not all((msg_signature, timestamp, nonce)):
            raise HTTPException(status_code=400, detail='Missing message parameters')
        encrypted_xml = await request.body()
        try:
            # Preserve the established wechatpy decryption argument order.
            decrypted_xml = services.crypto.decrypt_message(encrypted_xml, msg_signature, timestamp, nonce)
        except (InvalidSignatureException, InvalidAppIdException):
            logger.warning('Invalid encrypted WeChat message')
            raise HTTPException(status_code=403, detail='Invalid WeChat message') from None
        except Exception:
            logger.warning('Malformed encrypted WeChat message')
            raise HTTPException(status_code=400, detail='Malformed WeChat message') from None
        try:
            message = parse_message(decrypted_xml)
        except Exception:
            logger.warning('Failed to parse WeChat XML')
            return PlainTextResponse('success')
        openid = getattr(message, 'source', None)
        logger.info('Received WeChat message type=%s openid=%s', message.type, mask_openid(openid))
        if not openid:
            return PlainTextResponse('success')
        if message.type != 'text':
            reply_text = '当前测试版本只支持文字消息。'
        else:
            reply_text = await services.router.handle_text(openid, message.content or '')
        encrypted_reply = build_encrypted_reply(services.crypto, message, reply_text, nonce, timestamp)
        logger.info('WeChat request duration=%.3fs', time.monotonic() - started)
        return Response(content=encrypted_reply, media_type='application/xml')

    return application


# Importing the ASGI app starts neither the CLI nor a database connection.
app = create_app()


def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error('Configuration error: %s', exc)
        return 1
    application = create_app(settings, interactive_cli=True)
    server = uvicorn.Server(uvicorn.Config(application, host=settings.server.host, port=settings.server.port))
    application.state.shutdown = lambda: setattr(server, 'should_exit', True)
    server.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
