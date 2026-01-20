#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _post_webhook(webhook_url: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _post_chat_post_message(token: str, channel: str, text: str) -> None:
    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise RuntimeError("Slack API returned non-JSON response")
    if not data.get("ok", False):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown_error')}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: codex_notify_slack.py '<notification_json>'", file=sys.stderr)
        return 2

    try:
        notification = json.loads(sys.argv[1])
    except Exception:
        print("error: failed to parse notification JSON from argv[1]", file=sys.stderr)
        return 2

    if notification.get("type") != "agent-turn-complete":
        return 0

    last_msg = (
        notification.get("last-assistant-message")
        or notification.get("last_assistant_message")
        or notification.get("message")
        or ""
    )
    last_msg = str(last_msg).strip() or "(no assistant message)"

    session_id = notification.get("session-id") or notification.get("session_id") or ""
    cwd = notification.get("cwd") or ""
    model = notification.get("model") or ""

    header_bits = [b for b in [f"session={session_id}" if session_id else "", model, cwd] if b]
    header = "Codex: turn complete"
    if header_bits:
        header += f" ({' | '.join(header_bits)})"

    text = header + "\n" + _truncate(last_msg, 3500)

    try:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        channel = os.environ.get("SLACK_CHANNEL", "").strip()

        if webhook_url:
            _post_webhook(webhook_url, text)
            return 0

        if bot_token and channel:
            _post_chat_post_message(bot_token, channel, text)
            return 0

        print(
            "error: Slack not configured. Set either SLACK_WEBHOOK_URL or (SLACK_BOT_TOKEN and SLACK_CHANNEL).",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"error: failed to send Slack notification: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: failed to send Slack notification: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

