"""
Prompt evals for the calendar orchestrator.
Tests that prompt.py + gpt-4.1 produces correct JSON for real messages.

Usage:
    OPENAI_API_KEY=xxx python evals/test_prompt.py

No Modal, no Google Calendar — only the LLM logic is tested.
"""

import json
import os
import sys
from datetime import datetime, timezone

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.prompt import SYSTEM_PROMPT

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M (%A)")

PASS_COUNT = 0
FAIL_COUNT = 0


def empty_state():
    return {
        "intent": "null",
        "fields_json": "none",
        "awaiting_confirmation": "false",
        "event_history_json": "[]",
        "last_reply": "none",
    }


def state(intent="null", fields=None, awaiting=False, last_reply="none", history=None):
    return {
        "intent": intent,
        "fields_json": json.dumps(fields or {}, ensure_ascii=False),
        "awaiting_confirmation": str(awaiting).lower(),
        "event_history_json": json.dumps(history or [], ensure_ascii=False),
        "last_reply": last_reply,
    }


def call_llm(message: str, s: dict, conversation: list = None) -> dict:
    system = SYSTEM_PROMPT.format(today=TODAY, **s)
    messages = [{"role": "system", "content": system}]
    if conversation:
        messages.extend(conversation[-10:])
    messages.append({"role": "user", "content": message})

    resp = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=1024,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return json.loads(resp.choices[0].message.content)


def check(label: str, result: dict, assertions: dict):
    global PASS_COUNT, FAIL_COUNT
    failures = []

    for key, expected in assertions.items():
        # Support nested keys like "fields.end_time"
        parts = key.split(".")
        actual = result
        try:
            for part in parts:
                actual = actual[part]
        except (KeyError, TypeError):
            actual = None

        if callable(expected):
            ok = expected(actual)
        elif isinstance(expected, str):
            ok = str(actual).lower() == expected.lower() if actual is not None else False
        else:
            ok = actual == expected

        if not ok:
            failures.append(f"    {key}: expected {expected!r}, got {actual!r}")

    if failures:
        print(f"FAIL  {label}")
        for f in failures:
            print(f)
        FAIL_COUNT += 1
    else:
        print(f"PASS  {label}")
        PASS_COUNT += 1


# ── Test cases ────────────────────────────────────────────────────────────────

# 1. Full create with all fields
r = call_llm("boka tandläkare fredag 14-15", empty_state())
check("create: full message → ready=true", r, {"intent": "create", "ready": True})

# 2. Generic intent phrase — no subject
r = call_llm("boka ett event", empty_state())
check("create: generic phrase → ready=false, ask subject", r, {"intent": "create", "ready": False})

# 3. Subject but no time
r = call_llm("boka tandläkare", empty_state())
check("create: subject only → ready=false", r, {"intent": "create", "ready": False})

# 4. Bare number as end_time answer (PRIORITY 2 — must NOT switch to chat)
r = call_llm("23", state(intent="create", fields={"subject": "tandläkare", "date": "2026-03-07", "start_time": "21:00", "missing": ["end_time"]}))
check("create: '23' continues active intent", r, {"intent": "create"})

# 5. Bare number as start_time answer
r = call_llm("14", state(intent="create", fields={"subject": "gympass", "date": "2026-03-07"}, awaiting=False))
check("create: '14' continues active intent", r, {"intent": "create"})

# 6. Greeting during active create → chat + reset
r = call_llm("hej", state(intent="create", fields={"subject": "tandläkare"}))
check("create: 'hej' → chat reset", r, {"intent": "chat"})

# 7. Thanks → chat (warm reply, not a booking)
r = call_llm("tack", empty_state())
check("chat: 'tack' → intent=chat", r, {"intent": "chat"})

# 8. Duration calculation
r = call_llm("gympass fredag 18:00 i en timme", empty_state())
check("create: duration → end_time calculated", r, {
    "intent": "create",
    "fields.end_time": lambda v: v in ("19:00", "19:00:00"),
})

# 9. MIDNIGHT RULE
r = call_llm("möte med Anna fredag 22:00-00:00", empty_state())
check("create: midnight rule → end_datetime next day", r, {
    "intent": "create",
    "fields.end_datetime": lambda v: v is not None and "T00:00" in str(v) and str(v) > "2026-03-06T22:00:00",
})

# 10. Update intent
r = call_llm("flytta tandläkaren till måndag 10-11", empty_state())
check("update: basic reschedule", r, {"intent": "update"})

# 11. Update title only
r = call_llm("ändra titeln på mötet fredag till Projektmöte", empty_state())
check("update: title change", r, {
    "intent": "update",
    "fields.changes.summary": lambda v: v is not None,
})

# 12. Delete — turn 1: ask for confirmation
r = call_llm("ta bort tandläkaren", empty_state())
check("delete: turn 1 → awaiting_confirmation=true, ready=false", r, {
    "intent": "delete",
    "ready": False,
    "awaiting_confirmation": True,
})

# 13. Delete — turn 2a: user confirms
r = call_llm("ja", state(intent="delete", fields={"event_identifier": {"keywords": ["tandläkare"], "date": None}, "confirmed": False}, awaiting=True))
check("delete: 'ja' → ready=true, confirmed=true", r, {
    "intent": "delete",
    "ready": True,
    "fields.confirmed": True,
})

# 14. Delete — turn 2b: user cancels
r = call_llm("nej", state(intent="delete", fields={"event_identifier": {"keywords": ["tandläkare"], "date": None}, "confirmed": False}, awaiting=True))
check("delete: 'nej' → cancelled=true", r, {"cancelled": True})

# 15. Last reply recall
r = call_llm("har du bokat den?", state(last_reply="Tandläkare inbokat fredag 15/1 kl 14:00–15:00."))
check("chat: last reply recall → intent=chat", r, {"intent": "chat"})

# ── Summary ───────────────────────────────────────────────────────────────────
total = PASS_COUNT + FAIL_COUNT
print(f"\n{PASS_COUNT}/{total} passed", "✓" if FAIL_COUNT == 0 else "✗")
sys.exit(0 if FAIL_COUNT == 0 else 1)
