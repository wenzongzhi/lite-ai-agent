# lite-ai-agent

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square" alt="Python 3.10+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square" alt="许可证：Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Status-Experimental-orange?style=flat-square" alt="状态：实验阶段" />
</p>

一个将微信公众号与豆包 API 连接起来的轻量级 AI 助手。服务基于 FastAPI，接收微信 POST 的加密 XML，校验签名并进行 AES 解密，将用户的文字消息发送到火山方舟的豆包模型，再把返回的 `choices[0].message.content` 组成微信文本回复，经 AES 加密后返回给微信。

## 消息处理流程

```text
用户发送文字消息
    → 微信 POST /wechat
    → 签名校验、AES 解密、XML 解析
    → 调用豆包 Chat Completions API
    → 提取 content，生成回复 XML 并进行 AES 加密
    → 微信向用户展示回复
```

- 豆包在 **3.5 秒**内完成时，直接返回答案。
- 超过 3.5 秒时，先回复处理提示，豆包任务继续在后台运行。用户稍后发送 **`结果`** 查询答案。
- 普通用户使用 **ai-answer**，只进行豆包问答，不开放工具。主动启用 Agent 的用户使用 **ai-agent**，支持原生 Function Calling、有限步数的工具执行和记忆上下文。
- 同一个用户有任务正在处理时，新问题会收到等待提示。
- 非文字消息会收到仅支持文字消息的提示。

## 运行条件

- Python **3.10 或更高版本**。
- 可配置服务器回调的微信公众号，以及对应的 Token、EncodingAESKey 和开发者 AppID。
- 火山方舟 API Key，以及账号已开通的模型 ID 或 Endpoint ID。
- 微信服务器可访问的公网回调地址，以及能够访问火山方舟 API 的运行环境。
- 使用下文的本地调试方案时，需要在 Cloudflare 注册的域名，并在运行 `app.py` 的主机上安装 `cloudflared`。

## 安装

在项目目录中创建虚拟环境：

```shell
python -m venv .venv
```

在 Windows PowerShell 中激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

或在 Linux / macOS 中激活：

```shell
source .venv/bin/activate
```

安装依赖：

```shell
python -m pip install -r requirements.txt
```

`wechatpy[cryptography]` 包含消息加解密所需的依赖，安装方式参见 [wechatpy 官方安装文档](https://docs.wechatpy.org/zh-cn/stable/install.html)。当前仓库没有依赖锁定文件。

## 配置

将 `config.example.toml` 复制为 `config.toml`，填写必需的微信与豆包配置。Windows PowerShell：

```powershell
Copy-Item config.example.toml config.toml
```

Linux / macOS：

```shell
cp config.example.toml config.toml
```

配置优先级为 **环境变量 > config.toml > 内置默认值**。使用 `WECHAT_AGENT_CONFIG` 指定其他 TOML 路径。本地配置、`.env` 和数据库文件已被 Git 忽略；程序不会自动加载 `.env`。

| 环境变量 | TOML 配置 / 说明 |
| --- | --- |
| `WECHAT_TOKEN` | `wechat.token`：与微信公众号服务器配置中的 Token 一致 |
| `WECHAT_ENCODING_AES_KEY` | `wechat.encoding_aes_key`：自动校验并补齐 padding |
| `WECHAT_APP_ID` | `wechat.app_id`：开发者 AppID，区别于“原始 ID” |
| `WECHAT_APP_SECRET` | `wechat.app_secret`：可选，为后续集成预留 |
| `DOUBAO_API_KEY` | `doubao.api_key`：火山方舟 API Key |
| `DOUBAO_MODEL` | `doubao.model`：必填，已开通的模型 ID 或 `ep-xxxx` 形式的 Endpoint ID |
| `DOUBAO_BASE_URL` | `doubao.base_url`：默认 `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| `DOUBAO_HTTP_TIMEOUT_SECONDS` | `doubao.http_timeout_seconds`：默认 `120` 秒 |
| `FAST_REPLY_TIMEOUT_SECONDS` | `server.fast_reply_timeout_seconds`：默认 `3.5` 秒 |
| `AGENT_DB_PATH` | `database.path`：默认 `./data/agent.db` |
| `BRAVE_SEARCH_API_KEY` | `web_search.api_key`：仅用于可选的 Brave 搜索 |

Token、EncodingAESKey、AppID、豆包 API Key 和模型均为必填。启动时缺少配置会报告字段名，不输出凭据。`features`、`agent`、`web_search` 和 `calendar` 下的其他配置对应大写环境变量，例如 `FEATURES_AI_AGENT_ENABLED` 和 `AGENT_MAX_STEPS`。

豆包请求使用 Bearer API Key 认证，设置 `stream=False`、`max_tokens=1000`。每次请求包含固定的系统提示词和当前用户消息，系统提示词要求以纯文本回答。

## 启动服务

本地启动：

```shell
python app.py
```

默认监听 `127.0.0.1:8000`，下文的 Cloudflare Tunnel 方案使用该本地地址。需要直接监听外部连接时，可使用：

```shell
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

通过 `python app.py` 启动且标准输入为交互终端时，会同时开启本地管理员 CLI。CLI 在独立线程中运行，FastAPI 继续处理请求。通过 Uvicorn 启动或使用非交互输入时，不会启动控制台。

## 模式与本地 CLI

新用户默认使用普通问答。在微信中发送 `开启豆包agent功能` 可启用 Agent，发送 `关闭豆包agent功能` 返回普通问答。开关短语可以配置，不会调用豆包，用户状态保存在 SQLite。设置 `features.allow_user_agent_self_enable = false` 后，只能由管理员通过 CLI 启用用户。

本地控制台支持：

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

全局开关优先于用户模式，关闭功能后停止接受对应模式的新任务，`结果` 仍可查询已有任务。`config reload` 重载非敏感运行参数，凭据、数据库路径或监听设置变化时报告 `restart required`。CLI 修改仅对当前进程生效，不写回 TOML。`quit` 停止服务。控制台列表和日志中的 OpenID 均会脱敏。

## 工具与记忆

Agent 使用火山方舟的[原生 Function Calling](https://docs.volcengine.com/docs/ark/function-calling?lang=zh)。模型请求调用工具，由 Python 校验参数与用户权限、应用超时、执行注册的处理函数并限制结果大小。普通问答不会收到工具定义。

- `calculator`：通过 AST 白名单进行有限制的算术计算，不使用 `eval`。
- `memory_search`：仅搜索当前 OpenID 的精选记忆，最多返回五条；使用 FTS5，必要时回退到参数化 LIKE 查询。
- `fortune_telling`：由 Python 随机抽取结果，仅用于娱乐。
- `web_search`：可选的 Brave 搜索，返回精简的标题、URL 和摘要，默认关闭。设置 `web_search.enabled = true` 并配置 API Key 后启用。参见 [Brave API 文档](https://api-dashboard.search.brave.com/app/documentation/web-search/codes)。

Agent 自动加载最多 12 条最近消息与人工精选的简短摘要。使用 `memory save <openid> <type> <content>` 主动保存 preference、project、decision、profile、todo 或 summary 类型的记忆。摘要按用户更新，不会自动将闲聊写入长期记忆。默认上限为六个 Agent 步骤、每个工具 15 秒、每个工具结果 8000 字节。

日历目前提供默认关闭的 Provider 接口，Google OAuth 和真实事件操作暂缓。日历工具不会开放给模型，未来的写入工具必须要求明确确认。

## 使用 Cloudflare Tunnel 本地调试

本项目的本地调试流程使用 Cloudflare 域名和本地运行的 `cloudflared`，将请求转发到应用。例如，域名为 `example.com` 时，使用 `agent.example.com` 作为公网主机名：

```text
微信 → https://agent.example.com/wechat
     → Cloudflare Tunnel → 本地 cloudflared
     → http://127.0.0.1:8000/wechat
```

1. 在 Cloudflare 注册一个域名，例如 `example.com`。
2. 在 Cloudflare 控制台创建一个 Tunnel，例如命名为 `lite-ai-agent`。按照控制台的配置说明，在运行 `app.py` 的同一台主机上安装 `cloudflared`。
3. 为 Tunnel 添加公开应用路由（公网主机名），将主机名设为 `agent.example.com`，服务 URL 设为 `http://127.0.0.1:8000`，把该子域名映射到本地应用。
4. 在一个终端中启动 `python app.py`，在同一台主机的另一个终端中，使用 Cloudflare 提供的 Tunnel Token 运行 `cloudflared`：

   ```shell
   cloudflared tunnel run --token YOUR_TUNNEL_TOKEN
   ```

   将 `YOUR_TUNNEL_TOKEN` 替换为你的 Tunnel Token。安装和控制台配置的详细说明参见 [Cloudflare Tunnel 配置指南](https://developers.cloudflare.com/tunnel/get-started/)。

5. 在微信公众号后台打开**消息推送**配置，将 **`https://agent.example.com/wechat`** 填写为回调 URL。设置与应用一致的 Token 和 EncodingAESKey，消息加解密方式选择使用 AES 的**安全模式**。
6. 保持 `app.py` 和 `cloudflared` 同时运行，然后向公众号发送文字消息，测试完整流程。

公网回调使用 HTTPS，Tunnel 将请求转发到 `127.0.0.1:8000` 的本地 HTTP 服务，转发过程中保留 `/wechat` 路径。

## 接口

| 接口 | 行为 |
| --- | --- |
| `GET /wechat` | 接收 `signature`、`timestamp`、`nonce`、`echostr`；签名校验通过后原样返回 `echostr`，缺少参数或签名无效时返回 `404` |
| `POST /wechat` | 接收加密 XML，请求参数必须包含 `msg_signature`、`timestamp`、`nonce`；解密后处理消息并返回加密 XML 回复 |
| `GET /` | 返回 `404 Not Found` |

FastAPI 的 `/docs`、`/redoc` 和 `/openapi.json` 已关闭。直接用浏览器访问 `/wechat`，且未携带所需验证参数时，返回 404 是当前实现的预期行为，通过 Cloudflare 域名访问时也一样。

## 使用方法

1. 在微信中向公众号发送一个文字问题。
2. 如果豆包及时完成，公众号直接回复答案。
3. 如果收到处理中的提示，稍后发送 `结果` 查询答案。必须发送这个中文命令，`result` 不会被识别为查询命令。
4. 查询时任务仍在运行会收到等待提示；任务完成后返回答案；调用失败则提示重新发送问题。

发送 `结果` 只查询当前用户最近一次任务，不会发起新的豆包请求。后台任务完成后，需要用户主动查询才能收到答案。

## 持久化与当前限制

- SQLite 保存用户、消息、任务与精选记忆。完成的结果和用户 Agent 开关在重启后保留；未完成的任务标记为中断，并提示用户重新提问。
- 使用单个 worker 运行，以便问题请求和结果查询共享同一份任务状态。
- 普通问答仍逐个问题独立调用，Agent 则加载有限的最近上下文和精选记忆。
- 目前没有基于微信消息 ID 的重复请求去重，也没有记录的自动过期清理。
- 工具超时后停止等待结果；Python 无法强制终止工作线程中已经执行的同步函数。内置同步工具均为有边界的本地操作。

## 项目文件

```text
lite-ai-agent/
├── app.py                  # 微信 AES 适配与服务器 / CLI 启动
├── config.py               # 类型化配置与校验
├── config.example.toml     # 配置模板
├── services.py             # 服务构建与安全重载
├── agent/                  # 豆包适配、运行状态与 Agent Loop
├── tools/                  # 注册表、分发器与明确注册的工具
├── memory/                 # SQLite Schema、仓库与搜索
├── cli/                    # 本地命令分发与控制台线程
├── wechat/                 # 加解密辅助与消息 / 任务路由
├── tests/                  # 离线回归与单元测试
├── README.md
├── README.zh-CN.md
└── LICENSE
```

## 测试

```shell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试使用模拟的微信请求 / 豆包 / Brave 响应，以及真实的本地 AES / SQLite 操作，不调用外部 API。测试临时文件保存在 Git 忽略的 `.pytest_cache` 目录中。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
