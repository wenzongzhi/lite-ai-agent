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
# 1. 微信公众号配置
# ============================================================

WECHAT_TOKEN = "填写你的Token"

WECHAT_ENCODING_AES_KEY = "填写你的EncodingAESKey"

# 注意：
# 这里填写“开发者ID AppID”，不是“原始ID”
WECHAT_APP_ID = "填写你的AppID"


# ============================================================
# 2. 豆包 / 火山方舟配置
# ============================================================

# 在火山方舟控制台获取 API Key
ARK_API_KEY = "填写你的ARK_API_KEY"

# 填你实际开通的模型 ID
#
# 官方当前示例：
# doubao-seed-2-1-pro-260628
#
# 如果你使用的是 Endpoint ID，也可以填 ep-xxxx
DOUBAO_MODEL = "doubao-seed-2-1-pro-260628"

DOUBAO_API_URL = (
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
)


# ============================================================
# 3. 微信快速回复时间预算
# ============================================================

# 最多等豆包 3.5 秒
FAST_REPLY_TIMEOUT = 3.5

# 豆包自身 HTTP 请求允许更长时间
# 即使微信已经返回“稍后发送结果”，
# 后台任务仍然允许继续跑。
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
    微信后台给出的 EncodingAESKey 通常为 43 字符。
    wechatpy/base64 可能需要补 '=' padding。
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
# 当前测试版：
#
# 每个 OpenID 只保存最近一个 AI Job。
#
# key:
#     openid
#
# value:
#     AIJob
#
# 将来可以替换成 SQLite。
# ------------------------------------------------------------

jobs: dict[str, AIJob] = {}


# ============================================================
# 7. OpenID 日志脱敏
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
# 8. 调用豆包 API
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

        # 非流式。
        # 我们需要得到完整答案后再组成微信 XML。
        "stream": False,

        # 测试阶段先控制回复长度
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

    # HTTP 层异常
    response.raise_for_status()

    data = response.json()

    # --------------------------------------------------------
    # 防御性检查
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
# 9. AI 后台任务
# ============================================================

async def run_ai_job(
    openid: str,
    job_id: str,
    question: str,
) -> str:
    """
    调用豆包，并把结果保存到 jobs。

    很重要：
    即使微信的 3.5 秒等待已经超时，
    此 coroutine 仍然继续运行。
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
        # 防止旧任务覆盖新任务
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
# 10. 创建 AI Job
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
    # create_task：
    #
    # 任务脱离当前 HTTP 等待逻辑运行。
    #
    # 我们把 task 保存到 AIJob 中，
    # 避免 Task 没有强引用。
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
# 11. AES 被动回复
# ============================================================

def build_encrypted_reply(
    message,
    content: str,
    nonce: str,
    timestamp: str,
) -> str:
    """
    构造微信被动文本回复，然后 AES 加密。
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
# 12. 处理“结果”
# ============================================================

def get_job_result(
    openid: str,
) -> str:

    job = jobs.get(
        openid
    )

    # --------------------------------------------------------
    # 没有任务
    # --------------------------------------------------------

    if job is None:

        return (
            "当前没有正在处理或等待查看的任务。"
        )

    # --------------------------------------------------------
    # 还在运行
    # --------------------------------------------------------

    if job.status == "processing":

        return (
            "任务仍在处理中，请稍后再试。"
        )

    # --------------------------------------------------------
    # 完成
    # --------------------------------------------------------

    if job.status == "done":

        if not job.answer:
            return (
                "任务已经完成，但没有获得有效结果。"
            )

        return job.answer

    # --------------------------------------------------------
    # 调用失败
    # --------------------------------------------------------

    if job.status == "error":

        return (
            "任务处理失败，请重新发送问题。"
        )

    return (
        "未知任务状态，请重新发送问题。"
    )


# ============================================================
# 13. 首页
# ============================================================

@app.get("/")
async def root():
    return PlainTextResponse(
        "Not Found",
        status_code=404,
    )


# ============================================================
# 14. 微信 GET 验证
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
    # 普通浏览器直接访问 /wechat，
    # 或请求缺少任何一个微信必需参数时，
    # 不让 FastAPI 返回详细的 422 参数信息。
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

        # 不向客户端暴露“这是微信签名验证接口”
        return PlainTextResponse(
            "Not Found",
            status_code=404,
        )

    # 只有真正通过微信签名校验后，
    # 才返回 echostr 给微信服务器。
    return PlainTextResponse(
        echostr,
        status_code=200,
    )

# ============================================================
# 15. 微信 AES POST
# ============================================================

@app.post("/wechat")
async def wechat_post(
    request: Request,
):

    request_start = time.monotonic()

    # --------------------------------------------------------
    # URL 参数
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
    # 微信加密 XML
    # --------------------------------------------------------

    encrypted_xml = (
        await request.body()
    )

    # --------------------------------------------------------
    # AES 解密
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
    # 暂时只处理文字
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
    # 用户发送“结果”
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
    # 普通问题
    # ========================================================

    # --------------------------------------------------------
    # 如果当前已经有一个任务正在运行，
    # 暂时不允许同一用户同时启动第二个。
    #
    # 防止测试阶段任务互相覆盖。
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
    # 启动新的豆包任务
    # --------------------------------------------------------

    job = start_ai_job(
        openid,
        user_text,
    )

    try:

        # ----------------------------------------------------
        # 最关键的逻辑：
        #
        # 最多只等待 3.5 秒。
        #
        # shield() 的作用：
        #
        # wait_for 超时后，
        # 不取消真正运行的豆包 Task。
        # ----------------------------------------------------

        answer = await asyncio.wait_for(
            asyncio.shield(
                job.task
            ),
            timeout=FAST_REPLY_TIMEOUT,
        )

        # ====================================================
        # 豆包 3.5 秒以内完成
        # ====================================================

        reply_text = answer

        logger.info(
            "Doubao fast reply completed."
        )

    except asyncio.TimeoutError:

        # ====================================================
        # 超过 3.5 秒
        #
        # job.task 仍然继续运行。
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
    # 生成微信 AES 被动回复
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