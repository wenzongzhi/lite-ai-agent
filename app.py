import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from starlette.exceptions import HTTPException as StarletteHTTPException

from wechatpy import parse_message
from wechatpy.crypto import WeChatCrypto
from wechatpy.exceptions import (
    InvalidAppIdException,
    InvalidSignatureException,
)
from wechatpy.replies import create_reply
from wechatpy.utils import check_signature


# ============================================================
# 1. WeChat official account configuration
# ============================================================

WECHAT_TOKEN = "填写你的Token"

WECHAT_ENCODING_AES_KEY = "填写你的EncodingAESKey"

# Note:
# Use the developer AppID here, not the original account ID.
WECHAT_APP_ID = "填写你的AppID"


# ============================================================
# 2. Doubao / Volcengine Ark configuration
# ============================================================

# Obtain the API key from the Volcengine Ark console.
ARK_API_KEY = "填写你的ARK_API_KEY"

# Set the model ID enabled for your account.
#
# Current official example:
# doubao-seed-2-1-pro-260628
#
# If you use an endpoint ID, you can also set it to ep-xxxx.
DOUBAO_MODEL = "doubao-seed-2-1-pro-260628"

DOUBAO_API_URL = (
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
)


# ============================================================
# 3. WeChat fast reply time budget
# ============================================================

# Wait up to 3.5 seconds for Doubao.
FAST_REPLY_TIMEOUT = 3.5

# Allow more time for the Doubao HTTP request itself.
# The background task continues even after WeChat receives
# a reply asking the user to query the result later.
DOUBAO_HTTP_TIMEOUT = 120.0


# ============================================================
# 4. FastAPI
# ============================================================

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return PlainTextResponse("Not Found", status_code=404)

    return PlainTextResponse("Error", status_code=exc.status_code)
    
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# 5. EncodingAESKey padding
# ============================================================

def normalize_encoding_aes_key(key: str) -> str:
    """
    The EncodingAESKey from WeChat is usually 43 characters long.
    wechatpy/base64 may require additional '=' padding.
    """

    key = key.strip()

    missing_padding = (-len(key)) % 4

    if missing_padding:
        key += "=" * missing_padding

    return key


crypto = WeChatCrypto(
    WECHAT_TOKEN,
    normalize_encoding_aes_key(
        WECHAT_ENCODING_AES_KEY
    ),
    WECHAT_APP_ID,
)


# ============================================================
# 6. AI Job
# ============================================================

@dataclass
class AIJob:
    job_id: str

    question: str

    status: str
    # processing
    # done
    # error

    answer: Optional[str] = None

    error: Optional[str] = None

    created_at: float = 0

    task: Optional[asyncio.Task] = None


# ------------------------------------------------------------
# Current test version:
#
# Keep only the latest AI job for each OpenID.
#
# key:
#     openid
#
# value:
#     AIJob
#
# This storage can be replaced with SQLite in the future.
# ------------------------------------------------------------

jobs: dict[str, AIJob] = {}


# ============================================================
# 7. Mask OpenIDs in logs
# ============================================================

def mask_openid(
    openid: Optional[str],
) -> str:

    if not openid:
        return "<empty>"

    if len(openid) <= 10:
        return "***"

    return (
        openid[:5]
        + "..."
        + openid[-5:]
    )


# ============================================================
# 8. Call the Doubao API
# ============================================================

async def call_doubao(
    question: str,
) -> str:

    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DOUBAO_MODEL,

        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个通过微信公众号与用户交流的AI助手。"
                    "请直接回答用户的问题。"
                    "回答使用纯文本，不要使用复杂Markdown格式。"
                ),
            },
            {
                "role": "user",
                "content": question,
            },
        ],

        # Use a non-streaming response.
        # Wait for the complete answer before building the WeChat XML.
        "stream": False,

        # Limit the response length during testing.
        "max_tokens": 1000,
    }

    logger.info(
        "Calling Doubao API..."
    )

    async with httpx.AsyncClient(
        timeout=DOUBAO_HTTP_TIMEOUT
    ) as client:

        response = await client.post(
            DOUBAO_API_URL,
            headers=headers,
            json=payload,
        )

    # Raise an exception for HTTP errors.
    response.raise_for_status()

    data = response.json()

    # --------------------------------------------------------
    # Validate the response structure.
    # --------------------------------------------------------

    choices = data.get("choices")

    if not choices:
        raise RuntimeError(
            f"Doubao returned no choices: {data}"
        )

    message = choices[0].get(
        "message",
        {}
    )

    answer = message.get(
        "content"
    )

    if not answer:
        raise RuntimeError(
            f"Doubao returned empty content: {data}"
        )

    logger.info(
        "Doubao API completed."
    )

    return answer.strip()


# ============================================================
# 9. Background AI task
# ============================================================

async def run_ai_job(
    openid: str,
    job_id: str,
    question: str,
) -> str:
    """
    Call Doubao and save the result in jobs.

    Important:
    This coroutine continues running even after
    WeChat's 3.5-second wait has timed out.
    """

    logger.info(
        "AI job started: "
        "job_id=%s openid=%s",
        job_id,
        mask_openid(openid),
    )

    try:

        answer = await call_doubao(
            question
        )

        # ----------------------------------------------------
        # Prevent an older job from overwriting a newer job.
        # ----------------------------------------------------

        current_job = jobs.get(
            openid
        )

        if (
            current_job is not None
            and current_job.job_id == job_id
        ):

            current_job.status = "done"
            current_job.answer = answer

            logger.info(
                "AI job completed: "
                "job_id=%s",
                job_id,
            )

        return answer

    except Exception as exc:

        logger.exception(
            "AI job failed: job_id=%s",
            job_id,
        )

        current_job = jobs.get(
            openid
        )

        if (
            current_job is not None
            and current_job.job_id == job_id
        ):

            current_job.status = "error"
            current_job.error = str(exc)

        raise


# ============================================================
# 10. Create an AI job
# ============================================================

def start_ai_job(
    openid: str,
    question: str,
) -> AIJob:

    job_id = uuid.uuid4().hex

    job = AIJob(
        job_id=job_id,
        question=question,
        status="processing",
        created_at=time.time(),
    )

    # --------------------------------------------------------
    # create_task:
    #
    # Run the task independently of the current HTTP wait.
    #
    # Store the task in AIJob to retain a strong reference.
    # --------------------------------------------------------

    task = asyncio.create_task(
        run_ai_job(
            openid,
            job_id,
            question,
        )
    )

    job.task = task

    jobs[openid] = job

    return job


# ============================================================
# 11. AES-encrypted passive reply
# ============================================================

def build_encrypted_reply(
    message,
    content: str,
    nonce: str,
    timestamp: str,
) -> str:
    """
    Build a WeChat passive text reply, then encrypt it with AES.
    """

    reply = create_reply(
        content,
        message=message,
    )

    reply_xml = reply.render()

    encrypted_xml = crypto.encrypt_message(
        reply_xml,
        nonce,
        timestamp,
    )

    return encrypted_xml


# ============================================================
# 12. Handle the result query command
# ============================================================

def get_job_result(
    openid: str,
) -> str:

    job = jobs.get(
        openid
    )

    # --------------------------------------------------------
    # No job exists.
    # --------------------------------------------------------

    if job is None:

        return (
            "当前没有正在处理或等待查看的任务。"
        )

    # --------------------------------------------------------
    # The job is still running.
    # --------------------------------------------------------

    if job.status == "processing":

        return (
            "任务仍在处理中，请稍后再试。"
        )

    # --------------------------------------------------------
    # The job has completed.
    # --------------------------------------------------------

    if job.status == "done":

        if not job.answer:
            return (
                "任务已经完成，但没有获得有效结果。"
            )

        return job.answer

    # --------------------------------------------------------
    # The API call failed.
    # --------------------------------------------------------

    if job.status == "error":

        return (
            "任务处理失败，请重新发送问题。"
        )

    return (
        "未知任务状态，请重新发送问题。"
    )


# ============================================================
# 13. Root endpoint
# ============================================================

@app.get("/")
async def root():
    return PlainTextResponse(
        "Not Found",
        status_code=404,
    )


# ============================================================
# 14. WeChat GET verification
# ============================================================

@app.get(
    "/wechat",
    response_class=PlainTextResponse,
)
async def wechat_get(
    signature: str | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
    echostr: str | None = None,
):
    # For direct browser visits to /wechat or requests missing any
    # required WeChat parameter, avoid returning FastAPI's detailed
    # 422 validation response.
    if not all([
        signature,
        timestamp,
        nonce,
        echostr,
    ]):
        return PlainTextResponse(
            "Not Found",
            status_code=404,
        )

    try:

        check_signature(
            WECHAT_TOKEN,
            signature,
            timestamp,
            nonce,
        )

    except InvalidSignatureException:

        logger.warning(
            "Invalid WeChat GET signature."
        )

        # Do not reveal that this endpoint verifies WeChat signatures.
        return PlainTextResponse(
            "Not Found",
            status_code=404,
        )

    # Return echostr to the WeChat server only after
    # the WeChat signature has been verified.
    return PlainTextResponse(
        echostr,
        status_code=200,
    )

# ============================================================
# 15. WeChat AES POST handler
# ============================================================

@app.post("/wechat")
async def wechat_post(
    request: Request,
):

    request_start = time.monotonic()

    # --------------------------------------------------------
    # URL parameters
    # --------------------------------------------------------

    msg_signature = (
        request.query_params.get(
            "msg_signature"
        )
    )

    timestamp = (
        request.query_params.get(
            "timestamp"
        )
    )

    nonce = (
        request.query_params.get(
            "nonce"
        )
    )

    if not (
        msg_signature
        and timestamp
        and nonce
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Missing msg_signature/"
                "timestamp/nonce"
            ),
        )

    # --------------------------------------------------------
    # Encrypted WeChat XML
    # --------------------------------------------------------

    encrypted_xml = (
        await request.body()
    )

    # --------------------------------------------------------
    # AES decryption
    # --------------------------------------------------------

    try:

        decrypted_xml = (
            crypto.decrypt_message(
                encrypted_xml,
                msg_signature,
                timestamp,
                nonce,
            )
        )

    except (
        InvalidSignatureException,
        InvalidAppIdException,
    ):

        logger.exception(
            "WeChat AES decrypt failed."
        )

        raise HTTPException(
            status_code=403,
            detail="Invalid WeChat message",
        )

    # --------------------------------------------------------
    # XML -> message
    # --------------------------------------------------------

    try:

        message = parse_message(
            decrypted_xml
        )

    except Exception:

        logger.exception(
            "Failed to parse WeChat XML."
        )

        return PlainTextResponse(
            "success"
        )

    openid = getattr(
        message,
        "source",
        None,
    )

    logger.info(
        "Received WeChat message: "
        "type=%s openid=%s",
        message.type,
        mask_openid(openid),
    )

    # --------------------------------------------------------
    # Only text messages are currently supported.
    # --------------------------------------------------------

    if message.type != "text":

        reply_text = (
            "当前测试版本只支持文字消息。"
        )

        encrypted_reply = (
            build_encrypted_reply(
                message,
                reply_text,
                nonce,
                timestamp,
            )
        )

        return Response(
            content=encrypted_reply,
            media_type="application/xml",
        )

    user_text = (
        message.content or ""
    ).strip()

    # ========================================================
    # The user sends the result query command.
    # ========================================================

    if user_text == "结果":

        reply_text = get_job_result(
            openid
        )

        encrypted_reply = (
            build_encrypted_reply(
                message,
                reply_text,
                nonce,
                timestamp,
            )
        )

        elapsed = (
            time.monotonic()
            - request_start
        )

        logger.info(
            "Result query replied in %.3f s",
            elapsed,
        )

        return Response(
            content=encrypted_reply,
            media_type="application/xml",
        )

    # ========================================================
    # Regular question
    # ========================================================

    # --------------------------------------------------------
    # If a job is already running, do not allow the same user
    # to start a second job concurrently.
    #
    # Prevent jobs from overwriting each other during testing.
    # --------------------------------------------------------

    existing_job = jobs.get(
        openid
    )

    if (
        existing_job is not None
        and existing_job.status == "processing"
    ):

        reply_text = (
            "当前已有一个任务正在处理中。"
            "请稍后发送“结果”查看。"
        )

        encrypted_reply = (
            build_encrypted_reply(
                message,
                reply_text,
                nonce,
                timestamp,
            )
        )

        return Response(
            content=encrypted_reply,
            media_type="application/xml",
        )

    # --------------------------------------------------------
    # Start a new Doubao job.
    # --------------------------------------------------------

    job = start_ai_job(
        openid,
        user_text,
    )

    try:

        # ----------------------------------------------------
        # Key behavior:
        #
        # Wait for at most 3.5 seconds.
        #
        # Purpose of shield():
        #
        # Keep the underlying Doubao task running
        # when wait_for times out.
        # ----------------------------------------------------

        answer = await asyncio.wait_for(
            asyncio.shield(
                job.task
            ),
            timeout=FAST_REPLY_TIMEOUT,
        )

        # ====================================================
        # Doubao completes within 3.5 seconds.
        # ====================================================

        reply_text = answer

        logger.info(
            "Doubao fast reply completed."
        )

    except asyncio.TimeoutError:

        # ====================================================
        # The 3.5-second wait has timed out.
        #
        # job.task continues running.
        # ====================================================

        reply_text = (
            "这个问题需要更多时间处理。"
            "请稍后发送“结果”。"
        )

        logger.info(
            "Doubao exceeded %.1f s; "
            "returning processing message.",
            FAST_REPLY_TIMEOUT,
        )

    except Exception:

        logger.exception(
            "Doubao quick call failed."
        )

        reply_text = (
            "AI 服务暂时出现异常，"
            "请稍后重新发送问题。"
        )

    # --------------------------------------------------------
    # Build an AES-encrypted WeChat passive reply.
    # --------------------------------------------------------

    encrypted_reply = (
        build_encrypted_reply(
            message,
            reply_text,
            nonce,
            timestamp,
        )
    )

    elapsed = (
        time.monotonic()
        - request_start
    )

    logger.info(
        "WeChat response completed "
        "in %.3f seconds.",
        elapsed,
    )

    return Response(
        content=encrypted_reply,
        media_type="application/xml",
    )


# ============================================================
# 16. Main
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
    )
