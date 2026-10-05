# lite-ai-agent

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square" alt="Python 3.10+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square" alt="License: Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Status-Experimental-orange?style=flat-square" alt="Status: Experimental" />
</p>

A lightweight AI assistant that connects a WeChat Official Account to the Doubao API. Built with FastAPI, the service receives encrypted XML via WeChat POST requests, verifies the signature, decrypts the message with AES, and sends the user's text to a Doubao model on Volcengine Ark. It then turns `choices[0].message.content` into a WeChat text reply, encrypts the reply with AES, and returns it to WeChat.

## Message Flow

```text
User sends a text message
    → WeChat POST /wechat
    → Signature verification, AES decryption, and XML parsing
    → Doubao Chat Completions API
    → Extract content, build reply XML, and encrypt it with AES
    → WeChat displays the reply to the user
```

- If Doubao completes within **3.5 seconds**, the answer is returned immediately.
- If it takes longer, the service returns a processing notice while the Doubao task continues in the background. The user can send **`结果`** (Chinese for "result") later to retrieve the answer.
- If the same user already has a running task, new questions receive a waiting notice.
- Non-text messages receive a notice explaining that only text messages are supported.

## Requirements

- Python **3.10 or later**.
- A WeChat Official Account with server callback configuration available, plus its Token, EncodingAESKey, and developer AppID.
- A Volcengine Ark API key and a model ID or endpoint ID enabled for your account.
- A public callback URL reachable by WeChat and a runtime environment that can access the Volcengine Ark API.
- For the local debugging setup below, a domain registered with Cloudflare and `cloudflared` installed on the machine running `app.py`.

## Installation

Create a virtual environment in the project directory:

```shell
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or activate it on Linux / macOS:

```shell
source .venv/bin/activate
```

Install the dependencies:

```shell
python -m pip install fastapi uvicorn httpx "wechatpy[cryptography]"
```

`wechatpy[cryptography]` includes the dependencies needed for message encryption and decryption; see the [official wechatpy installation guide](https://docs.wechatpy.org/zh-cn/stable/install.html). The repository currently has no dependency lock file.

## Configuration

Before starting the service, edit the configuration constants at the top of `app.py`:

| Setting | Description |
| --- | --- |
| `WECHAT_TOKEN` | Must match the Token in the WeChat Official Account's server configuration |
| `WECHAT_ENCODING_AES_KEY` | The EncodingAESKey provided by WeChat; the code automatically adds Base64 padding |
| `WECHAT_APP_ID` | The developer AppID of the WeChat Official Account, rather than its original account ID |
| `ARK_API_KEY` | The API key obtained from the Volcengine Ark console |
| `DOUBAO_MODEL` | An enabled model ID or an endpoint ID such as `ep-xxxx`; the code defaults to `doubao-seed-2-1-pro-260628` |
| `DOUBAO_API_URL` | Default endpoint: `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| `FAST_REPLY_TIMEOUT` | Time to wait for an immediate Doubao reply; defaults to `3.5` seconds |
| `DOUBAO_HTTP_TIMEOUT` | HTTP timeout for the Doubao request; defaults to `120.0` seconds |

Configuration is currently defined directly in the source code. The application does not automatically read environment variables or `.env` files. Replace the placeholder credentials before starting it.

Doubao requests use Bearer API key authentication with `stream=False` and `max_tokens=1000`. Each request contains a fixed system prompt and the current user message. The system prompt asks for plain-text answers.

## Running the Service

Start the application locally:

```shell
python app.py
```

By default, it listens on `127.0.0.1:8000`, which is the local address used by the Cloudflare Tunnel setup below. To listen for external connections directly, you can run:

```shell
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

## Local Debugging with Cloudflare Tunnel

The project's local debugging workflow uses a Cloudflare domain and a local `cloudflared` process to forward requests to the application. For example, if your domain is `example.com`, use `agent.example.com` as the public hostname:

```text
WeChat → https://agent.example.com/wechat
       → Cloudflare Tunnel → local cloudflared
       → http://127.0.0.1:8000/wechat
```

1. Register a domain with Cloudflare, such as `example.com`.
2. In the Cloudflare dashboard, create a tunnel, for example named `lite-ai-agent`. Install `cloudflared` on the same machine as `app.py`, following the dashboard's setup instructions.
3. Add a published application route (public hostname) to the tunnel with hostname `agent.example.com` and service URL `http://127.0.0.1:8000`. This maps the subdomain to the local application.
4. Start `python app.py` in one terminal. In another terminal on the same machine, run `cloudflared` using the tunnel token from Cloudflare:

   ```shell
   cloudflared tunnel run --token YOUR_TUNNEL_TOKEN
   ```

   Replace `YOUR_TUNNEL_TOKEN` with your tunnel's token. See the [Cloudflare Tunnel setup guide](https://developers.cloudflare.com/tunnel/get-started/) for installation and dashboard details.

5. In the WeChat Official Account admin console, open the **Message Push** configuration and enter **`https://agent.example.com/wechat`** as the callback URL. Set the matching Token and EncodingAESKey, and select AES **Safe Mode** for message encryption.
6. Keep both `app.py` and `cloudflared` running, then send a text message to the Official Account to test the full flow.

The public callback uses HTTPS, while the tunnel forwards to the local HTTP service at `127.0.0.1:8000`. The `/wechat` path is preserved when forwarding requests.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /wechat` | Accepts `signature`, `timestamp`, `nonce`, and `echostr`; returns `echostr` unchanged after signature verification, or `404` if a parameter is missing or the signature is invalid |
| `POST /wechat` | Accepts encrypted XML with required query parameters `msg_signature`, `timestamp`, and `nonce`; decrypts and processes the message, then returns an encrypted XML reply |
| `GET /` | Returns `404 Not Found` |

FastAPI's `/docs`, `/redoc`, and `/openapi.json` endpoints are disabled. Visiting `/wechat` directly in a browser without the required verification parameters is expected to return 404, including through the Cloudflare hostname.

## Usage

1. Send a text question to the Official Account in WeChat.
2. If Doubao completes in time, the account replies with the answer immediately.
3. If you receive a processing notice, send `结果` later to query the result. Use this exact Chinese command; `result` is not a recognized command.
4. If the task is still running, you receive a waiting notice. Once it finishes, the answer is returned. If the call fails, you are asked to send the question again.

Sending `结果` only queries the current user's latest task and does not start a new Doubao request. After a background task finishes, the user must query the result to receive it.

## Current Limitations

- Tasks are stored in the process's in-memory `jobs` dictionary. Only the latest task is retained per OpenID, and tasks and results are lost when the service restarts.
- Run with a single worker so question requests and result queries share the same task state.
- Each question is sent to the model independently; there is no multi-turn conversation history.
- Duplicate requests are not deduplicated by WeChat message ID, and stored results have no automatic expiration or cleanup.

## Project Files

```text
lite-ai-agent/
├── app.py       # FastAPI service, WeChat encryption, Doubao calls, and task management
├── README.md    # Project documentation
└── LICENSE      # Apache License 2.0
```

## License

This project is licensed under the [Apache License 2.0](LICENSE).
