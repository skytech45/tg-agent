"""
agent/llm_engine.py — LLM decision engine.

Takes user context + message and returns a structured Action,
not just a text reply. The LLM decides WHAT to do, not just what to say.

Supported actions:
  - reply         → send text back to user
  - route_channel → forward message to a Telegram channel
  - request_payment → prompt user for UPI payment screenshot
  - verify_payment  → trigger OCR payment verification flow
  - escalate        → route to human agent channel
  - set_role        → change user role
  - collect_info    → ask follow-up questions (multi-step flow)
"""

import json
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from loguru import logger

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are an intelligent Telegram agent dispatcher.

Given a user's message and their context (role, history, payment status), 
decide what ACTION to take. Always respond with valid JSON only — no prose.

Available actions:
- reply: send a text message back
- request_payment: ask user to send UPI payment screenshot
- verify_payment: user has sent a screenshot, trigger OCR verification
- route_channel: forward a message to a channel (client/agent/payment_log)
- escalate: route to human agent (when query is too complex)
- set_role: change user's role (admin only)
- collect_info: ask the user for more information (specify 'question' field)

Response format:
{
  "action": "<action_name>",
  "reply_text": "<text to send user if action=reply or collect_info>",
  "channel": "<client|agent|payment_log> if action=route_channel",
  "role": "<new_role> if action=set_role",
  "question": "<question text> if action=collect_info",
  "confidence": 0.0-1.0,
  "reasoning": "<brief internal reasoning>"
}

Role context:
- client: regular user, may need to verify payment to access services
- agent: support agent, can see routed queries
- admin: full access, can change roles and view all logs

Always be helpful, concise, and action-oriented."""


async def decide_action(
    user_message: str,
    user_context: Dict[str, Any],
    history: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Run the LLM decision engine.

    Args:
        user_message: The latest message from the user.
        user_context: Full user context dict from Redis memory.
        history: Conversation history formatted for OpenAI.

    Returns:
        Parsed action dict with keys: action, reply_text, etc.
    """
    context_summary = (
        f"User role: {user_context.get('role', 'client')}\n"
        f"Payment verified: {user_context.get('payment_verified', False)}\n"
        f"Current flow state: {user_context.get('flow_state', 'none')}\n"
        f"User ID: {user_context.get('user_id')}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"User context:\n{context_summary}"},
        *history[-6:],  # Last 6 messages for context window efficiency
        {"role": "user", "content": user_message},
    ]

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=512,
        )
        raw = response.choices[0].message.content
        action = json.loads(raw)
        logger.debug(f"LLM decision for user {user_context.get('user_id')}: {action}")
        return action

    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}")
        return {"action": "reply", "reply_text": "Sorry, I ran into an issue. Please try again."}
    except Exception as e:
        logger.error(f"LLM engine error: {e}")
        return {"action": "reply", "reply_text": "An error occurred. Please try again later."}


async def summarise_history(history: List[Dict[str, str]]) -> str:
    """Compress long history into a short summary to save tokens."""
    if len(history) < 10:
        return ""
    messages = [
        {"role": "system", "content": "Summarise this conversation in 3 sentences."},
        *history,
    ]
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.3,
            max_tokens=150,
        )
        return response.choices[0].message.content
    except Exception:
        return ""
