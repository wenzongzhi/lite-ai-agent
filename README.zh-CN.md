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
python -m pip install fastapi uvicorn httpx "wechatpy[cryptography]"
```

`wechatpy[cryptography]` 包含消息加解密所需的依赖，安装方式参见 [wechatpy 官方安装文档](https://docs.wechatpy.org/zh-cn/stable/install.html)。当前仓库没有依赖锁定文件。

## 配置

启动前，修改 `app.py` 顶部的配置常量：

| 配置项 | 说明 |
| --- | --- |
| `WECHAT_TOKEN` | 与微信公众号服务器配置中的 Token 一致 |
| `WECHAT_ENCODING_AES_KEY` | 微信提供的 EncodingAESKey；代码会自动补齐 Base64 padding |
| `WECHAT_APP_ID` | 微信公众号的开发者 AppID，区别于公众号的“原始 ID” |
| `ARK_API_KEY` | 火山方舟控制台获取的 API Key |
| `DOUBAO_MODEL` | 已开通的模型 ID 或 `ep-xxxx` 形式的 Endpoint ID；代码默认值为 `doubao-seed-2-1-pro-260628` |
| `DOUBAO_API_URL` | 默认请求地址：`https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| `FAST_REPLY_TIMEOUT` | 等待豆包直接回复的时间，默认 `3.5` 秒 |
| `DOUBAO_HTTP_TIMEOUT` | 豆包 HTTP 请求的超时时间，默认 `120.0` 秒 |

当前配置直接定义在代码中，程序不会自动读取环境变量或 `.env` 文件。凭据占位文本需要替换后才能启动。

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

## 当前实现的限制

- 任务保存在进程内的 `jobs` 字典中，每个 OpenID 只保留最近一个任务；服务重启后任务和结果会丢失。
- 使用单个 worker 运行，以便问题请求和结果查询共享同一份任务状态。
- 每次问题独立调用模型，没有多轮对话历史。
- 目前没有基于微信消息 ID 的重复请求去重，也没有任务结果的自动过期清理。

## 项目文件

```text
lite-ai-agent/
├── app.py       # FastAPI 服务、微信消息加解密、豆包调用与任务管理
├── README.md    # 项目说明
└── LICENSE      # Apache License 2.0
```

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
