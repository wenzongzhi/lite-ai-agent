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
- Ordinary users use **ai-answer**, a dedicated Doubao Q&A path without tools. Users who opt in use **ai-agent**, with native Function Calling, bounded tool execution, and memory context.
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
python -m pip install -r requirements.txt
```

`wechatpy[cryptography]` includes the dependencies needed for message encryption and decryption; see the [official wechatpy installation guide](https://docs.wechatpy.org/zh-cn/stable/install.html). The repository currently has no dependency lock file.

## Configuration

Copy `config.example.toml` to `config.toml` and fill in the required WeChat and Doubao settings. On Windows PowerShell:

```powershell
Copy-Item config.example.toml config.toml
```

On Linux / macOS:

```shell
cp config.example.toml config.toml
```

Settings use **environment variable > config.toml > built-in default** precedence. Set `WECHAT_AGENT_CONFIG` to load an alternate TOML path. The local config, `.env` files, and database files are ignored by Git. `.env` files are not automatically loaded.

| Environment variable | TOML setting / description |
| --- | --- |
| `WECHAT_TOKEN` | `wechat.token`: must match the Official Account's server Token |
| `WECHAT_ENCODING_AES_KEY` | `wechat.encoding_aes_key`: validated and padded automatically |
| `WECHAT_APP_ID` | `wechat.app_id`: developer AppID, rather than the original account ID |
| `WECHAT_APP_SECRET` | `wechat.app_secret`: optional, reserved for future integrations |
| `DOUBAO_API_KEY` | `doubao.api_key`: Volcengine Ark API key |
| `DOUBAO_MODEL` | `doubao.model`: required enabled model ID or endpoint ID such as `ep-xxxx` |
| `DOUBAO_BASE_URL` | `doubao.base_url`: defaults to `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| `DOUBAO_HTTP_TIMEOUT_SECONDS` | `doubao.http_timeout_seconds`: defaults to `120` seconds |
| `FAST_REPLY_TIMEOUT_SECONDS` | `server.fast_reply_timeout_seconds`: defaults to `3.5` seconds |
| `AGENT_DB_PATH` | `database.path`: defaults to `./data/agent.db` |
| `BRAVE_SEARCH_API_KEY` | `web_search.api_key`: only needed for optional Brave search |

The Token, EncodingAESKey, AppID, Doubao API key, and model are required. Startup reports missing field names without printing secrets. Other fields in the `features`, `agent`, `web_search`, and `calendar` sections have corresponding uppercase environment names, such as `FEATURES_AI_AGENT_ENABLED` and `AGENT_MAX_STEPS`.

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

`python app.py` also starts a local administrator CLI when stdin is interactive. The CLI runs in a separate thread while FastAPI handles requests. Starting through Uvicorn or from non-interactive stdin does not start the console.

## Modes and Local CLI

New users default to ordinary Q&A. Send `开启豆包agent功能` in WeChat to opt in to Agent mode, or `关闭豆包agent功能` to return to ordinary Q&A. These phrases are configurable and do not call Doubao. The per-user setting persists in SQLite. Set `features.allow_user_agent_self_enable = false` to allow only the administrator CLI to enable users.

The local console accepts:

```text
help
status
enable ai-answer
disable ai-answer
enable ai-agent
disable ai-agent
show model
set model <model-id>
show fast-timeout
set fast-timeout <seconds>
config reload
users
jobs
user show <openid>
user agent enable <openid>
user agent disable <openid>
memory stats
memory search <openid> <query>
memory save <openid> <type> <content>
quit
```

Global switches take precedence over per-user mode. Disabling a feature prevents new jobs for that mode; `结果` can still retrieve existing results. `config reload` reloads non-secret runtime controls and reports `restart required` for changed credentials, database paths, or listener settings. CLI changes last for the current process and are not written to TOML. `quit` stops the server. OpenIDs in console listings and logs are masked.

## Tools and Memory

Agent mode uses Ark's [native Function Calling](https://docs.volcengine.com/docs/ark/function-calling?lang=zh). The model requests tools; Python validates arguments and user permissions, applies timeouts, executes registered handlers, and limits results. Ordinary Q&A never receives tool schemas.

- `calculator`: bounded arithmetic through an AST whitelist, without `eval`.
- `memory_search`: up to five curated memory matches belonging to the current OpenID, using FTS5 with a parameterized LIKE fallback.
- `fortune_telling`: a Python-generated random draw for entertainment only.
- `web_search`: optional Brave provider returning compact titles, URLs, and snippets; disabled by default. Set `web_search.enabled = true` and configure an API key to enable it. See the [Brave API documentation](https://api-dashboard.search.brave.com/app/documentation/web-search/codes).

Agent context automatically includes up to 12 recent messages and compact manually curated summaries. Use `memory save <openid> <type> <content>` to store a deliberate preference, project, decision, profile, todo, or summary. Summaries are updated per user; casual conversation is not automatically promoted to long-term memory. Default limits are six Agent steps, 15 seconds per tool, and 8000 bytes per tool result.

Calendar currently provides a disabled provider interface. Google OAuth and real event operations are deferred. Calendar tools are not exposed to the model; future write tools must require explicit confirmation.

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

## Persistence and Current Limitations

- SQLite stores users, messages, jobs, and curated memories. Completed results and Agent enablement survive restart; stale processing jobs are marked interrupted and the user is asked to send the question again.
- Run with a single worker so question requests and result queries share the same task state.
- Ordinary Q&A remains independent per question. Agent mode includes limited recent context and curated memory.
- Duplicate requests are not deduplicated by WeChat message ID, and stored records have no automatic expiration or cleanup.
- Tool timeouts stop waiting for results; Python cannot forcibly terminate a synchronous handler already running in a worker thread. Built-in synchronous tools are bounded and local.

## Project Files

```text
lite-ai-agent/
├── app.py                  # WeChat AES adapter and server / CLI startup
├── config.py               # Typed settings and validation
├── config.example.toml     # Configuration template
├── services.py             # Service construction and safe runtime reload
├── agent/                  # Doubao adapter, runtime state, and Agent Loop
├── tools/                  # Registry, dispatcher, and explicit tool handlers
├── memory/                 # SQLite schema, repository, and search
├── cli/                    # Local command dispatcher and console thread
├── wechat/                 # Crypto helpers and shared message / job router
├── tests/                  # Offline regression and unit tests
├── README.md
├── README.zh-CN.md
└── LICENSE
```

## Tests

```shell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use mocked WeChat transport / Doubao / Brave responses and real local AES / SQLite operations, without calling external APIs. Test temporary files stay under the ignored `.pytest_cache` directory.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
