from wechatpy.crypto import WeChatCrypto
from wechatpy.replies import create_reply


def mask_openid(openid: str | None) -> str:
    if not openid:
        return "<empty>"
    if len(openid) <= 10:
        return "***"
    return openid[:5] + "..." + openid[-5:]


def create_crypto(settings):
    # Settings already normalize AES padding; preserve the working wechatpy flow.
    return WeChatCrypto(settings.token, settings.encoding_aes_key, settings.app_id)


def build_encrypted_reply(crypto, message, content: str, nonce: str, timestamp: str) -> str:
    """Preserve the established passive text reply and AES encryption sequence."""
    reply = create_reply(content, message=message)
    reply_xml = reply.render()
    return crypto.encrypt_message(reply_xml, nonce, timestamp)
