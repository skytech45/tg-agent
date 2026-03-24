# 🤖 tg-agent

> Production-grade stateful Telegram AI agent — multi-user memory, LLM decision engine, UPI payment verification, role-based flows, and channel routing.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)
![Redis](https://img.shields.io/badge/Redis-7%2B-red?logo=redis)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **LLM Decision Engine** | GPT-4o-mini decides *actions*, not just replies — route, escalate, verify, collect |
| 💾 **Per-User Memory** | Redis-backed stateful context per user — history, role, flow state, metadata |
| 💳 **Payment Verification** | OCR reads UPI payment screenshots — validates TXN ID, amount, and status |
| 📡 **Channel Routing** | Auto-routes messages to client / agent / payment log Telegram channels |
| 👥 **Role-Based Flows** | Three roles: `client`, `agent`, `admin` — each with different permissions |
| ⚡ **FastAPI Webhook** | Production-ready webhook server with health endpoint |

---

## 🏗️ Architecture

```
tg-agent/
├── main.py                  # FastAPI app + webhook server + bot lifecycle
├── config.py                # Centralised settings (pydantic-settings)
├── requirements.txt         # Dependencies
├── .env.example             # Environment variable template
│
├── agent/
│   └── llm_engine.py        # LLM decision engine (OpenAI JSON mode)
│
├── bot/
│   └── handlers.py          # Telegram message + photo handlers
│
├── memory/
│   └── redis_memory.py      # Per-user Redis memory (history, state, metadata)
│
└── payment/
    └── ocr_verifier.py      # UPI screenshot OCR + payment validation
```

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/skytech45/tg-agent.git
cd tg-agent
pip install -r requirements.txt
```

> **OCR support:** Install Tesseract: `sudo apt install tesseract-ocr` (Ubuntu) or `brew install tesseract` (macOS)

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your tokens, Redis URL, OpenAI key, UPI ID, etc.
```

### 3. Start Redis

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### 4. Run the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Set Telegram webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/webhook"
```

---

## 🔄 How It Works

```
User Message
     │
     ▼
[Redis Memory] ──── Load user context (role, history, flow state)
     │
     ▼
[LLM Engine] ─────── Decide action (JSON output):
                      reply / request_payment / route_channel /
                      escalate / set_role / collect_info
     │
     ▼
[Handler] ────────── Execute action:
                      • Send reply
                      • Set flow state → await screenshot
                      • Forward to channel
                      • Notify human agent
     │
     ▼
[OCR Verifier] ────── If photo received in payment flow:
                       Download → preprocess → Tesseract OCR
                       → parse TXN ID, amount, status
                       → verify → update Redis → log to channel
```

---

## 👥 Roles

| Role | Permissions |
|---|---|
| `client` | Chat, make payments, check status |
| `agent` | Receive routed queries from client channel |
| `admin` | All permissions + change roles, view all logs |

Admins are defined by Telegram user ID in `TELEGRAM_ADMIN_IDS`.

---

## 🛠️ Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/pay` | Initiate UPI payment flow |
| `/status` | View your role and payment status |
| `/help` | Show available commands |

---

## ⚙️ Environment Variables

See `.env.example` for all options. Key variables:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_ADMIN_IDS` | Comma-separated admin user IDs |
| `REDIS_URL` | Redis connection string |
| `OPENAI_API_KEY` | OpenAI API key |
| `UPI_ID` | Your UPI ID for payment collection |
| `WEBHOOK_URL` | Public URL for Telegram webhook |

---

## ⚠️ Disclaimer

This project is for educational and personal use. Ensure compliance with Telegram's ToS and applicable laws when deploying payment verification systems.

---

## 📄 License

MIT License © [skytech45](https://github.com/skytech45)

---

*Part of an active developer portfolio — production-grade Python projects.*
