#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import fcntl  # type: ignore

    _HAVE_FCNTL = True
except Exception:
    _HAVE_FCNTL = False


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


def _post_chat_post_message(
    token: str,
    channel: str,
    text: str,
    *,
    thread_ts: str | None = None,
    reply_broadcast: bool = False,
) -> str:
    payload: dict = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
        payload["reply_broadcast"] = bool(reply_broadcast)

    api_base = os.environ.get("SLACK_API_BASE_URL", "https://slack.com/api").rstrip("/")
    req = urllib.request.Request(
        f"{api_base}/chat.postMessage",
        data=json.dumps(payload).encode("utf-8"),
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

    ts = data.get("ts")
    if not isinstance(ts, str) or not ts:
        raise RuntimeError("Slack API response missing ts")
    return ts


def _notify_send(title: str, body: str) -> None:
    if not shutil.which("notify-send"):
        raise RuntimeError("notify-send not found (install libnotify-bin or configure Slack env vars)")
    subprocess.run(["notify-send", title, body], check=True)


def _extract_session_id(notification: dict) -> str:
    candidates: list[object] = []

    for k in ("session-id", "session_id", "sessionId", "sessionID", "session id", "codex_session_id", "codexSessionId"):
        if k in notification:
            candidates.append(notification.get(k))

    sess = notification.get("session")
    if isinstance(sess, str):
        candidates.append(sess)
    elif isinstance(sess, dict):
        for k in ("id", "session-id", "session_id", "sessionId"):
            if k in sess:
                candidates.append(sess.get(k))

    for k in ("CODEX_SESSION_ID", "CODEX_SESSION", "CODEX_SESSIONID"):
        v = os.environ.get(k)
        if v:
            candidates.append(v)

    for c in candidates:
        s = str(c).strip() if c is not None else ""
        if s:
            return s
    return ""


def _session_key(session_id: str) -> str:
    # If Codex doesn't provide a stable session id in the notify payload, fall back to
    # the parent process id (Codex TUI keeps the same parent PID for a session).
    if session_id:
        return f"sid:{session_id}"
    return f"ppid:{os.getppid()}"


def _format_text(notification: dict) -> tuple[str, str]:
    last_msg = (
        notification.get("last-assistant-message")
        or notification.get("last_assistant_message")
        or notification.get("message")
        or ""
    )
    last_msg = str(last_msg).strip() or "(no assistant message)"

    sid = _extract_session_id(notification)
    cwd = str(notification.get("cwd") or "").strip()
    model = str(notification.get("model") or "").strip()

    header_bits = [b for b in [f"session={sid}" if sid else "", model, cwd] if b]
    title = "Codex: turn complete"
    if header_bits:
        title += f" ({' | '.join(header_bits)})"

    # Slack hard limit is 4000 chars; leave some headroom for safety.
    text = title + "\n" + _truncate(last_msg, 3500)
    return title, text


def _extract_cwd(notification: dict) -> str:
    for k in ("cwd", "workdir", "work_dir", "working_directory"):
        v = notification.get(k)
        if v is not None:
            s = str(v).strip()
            if s:
                return s
    return ""


def _task_title(notification: dict) -> str:
    cwd = _extract_cwd(notification)
    if cwd:
        return f"*Agent responses* : ({cwd})"
    return "*Agent responses*"


def _root_text(notification: dict, message: str) -> tuple[str, str]:
    title = _task_title(notification)
    # Root message includes title (+ dir) then message.
    text = title + "\n" + "\n" + _truncate(message, 3500)
    return title, text


def _reply_text(message: str) -> str:
    # Replies should be the message only to avoid clutter.
    return _truncate(message, 3900)


def _threads_path() -> Path:
    return Path(os.path.expanduser("~/.codex/slack_threads.json"))


def _load_threads() -> dict:
    p = _threads_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_threads(data: dict) -> None:
    p = _threads_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _with_threads_lock(fn):
    p = _threads_path()
    lock = p.with_suffix(p.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a", encoding="utf-8") as f:
        if _HAVE_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            if _HAVE_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _prune_threads(threads: dict, *, max_age_s: int = 7 * 24 * 3600) -> dict:
    now = int(time.time())
    pruned: dict = {}
    for sid, entry in threads.items():
        if not isinstance(sid, str) or not sid:
            continue
        if not isinstance(entry, dict):
            continue
        updated_at = entry.get("updated_at")
        if isinstance(updated_at, int) and (now - updated_at) > max_age_s:
            continue
        pruned[sid] = entry
    return pruned


def _debug_log(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


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

    # Keep message extraction consistent across output modes.
    title, text = _format_text(notification)
    message_only = (
        notification.get("last-assistant-message")
        or notification.get("last_assistant_message")
        or notification.get("message")
        or ""
    )
    message_only = str(message_only).strip() or "(no assistant message)"
    session_id = _extract_session_id(notification)
    session_key = _session_key(session_id)

    try:
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        channel = os.environ.get("SLACK_CHANNEL", "").strip()
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        debug_path = os.environ.get("CODEX_NOTIFY_DEBUG_PATH", "").strip()

        # Preferred: Slack Web API (supports threading).
        if bot_token and channel:

            def _send_slack_api() -> None:
                threads = _prune_threads(_load_threads())

                entry = threads.get(session_key)
                thread_ts: str | None = None
                if isinstance(entry, dict) and entry.get("channel") == channel:
                    v = entry.get("thread_ts")
                    if isinstance(v, str) and v:
                        thread_ts = v

                if thread_ts:
                    try:
                        _post_chat_post_message(
                            bot_token,
                            channel,
                            _reply_text(message_only),
                            thread_ts=thread_ts,
                            reply_broadcast=False,
                        )
                        threads[session_key] = {
                            "channel": channel,
                            "thread_ts": thread_ts,
                            "updated_at": int(time.time()),
                        }
                        _save_threads(threads)
                        if debug_path:
                            _debug_log(
                                debug_path,
                                {
                                    "ts": time.time(),
                                    "used": "slack_api_reply",
                                    "session_id": session_id,
                                    "session_key": session_key,
                                    "channel": channel,
                                    "thread_ts": thread_ts,
                                    "notification_keys": sorted(notification.keys()),
                                },
                            )
                        return
                    except RuntimeError as e:
                        # If the saved thread no longer exists, fall back to creating a new one.
                        if "thread_not_found" not in str(e):
                            raise

                # Start a new thread.
                root_title, root_text = _root_text(notification, message_only)
                ts = _post_chat_post_message(bot_token, channel, root_text)
                threads[session_key] = {"channel": channel, "thread_ts": ts, "updated_at": int(time.time())}
                _save_threads(threads)
                if debug_path:
                    _debug_log(
                        debug_path,
                        {
                            "ts": time.time(),
                            "used": "slack_api_root",
                            "session_id": session_id,
                            "session_key": session_key,
                            "channel": channel,
                            "thread_ts": ts,
                            "title": root_title,
                            "notification_keys": sorted(notification.keys()),
                        },
                    )

            _with_threads_lock(_send_slack_api)
            return 0

        # Fallback: incoming webhook (no threading).
        if webhook_url:
            root_title, root_text = _root_text(notification, message_only)
            _post_webhook(webhook_url, root_text)
            if debug_path:
                _debug_log(
                    debug_path,
                    {
                        "ts": time.time(),
                        "used": "webhook",
                        "session_id": session_id,
                        "session_key": session_key,
                        "title": root_title,
                        "notification_keys": sorted(notification.keys()),
                    },
                )
            return 0

        # Final fallback: desktop notification.
        root_title, root_text = _root_text(notification, message_only)
        _notify_send(root_title, _truncate(root_text, 900))
        if debug_path:
            _debug_log(
                debug_path,
                {
                    "ts": time.time(),
                    "used": "notify_send",
                    "session_id": session_id,
                    "session_key": session_key,
                    "title": root_title,
                    "notification_keys": sorted(notification.keys()),
                },
            )
        return 0
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"error: notify failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: notify failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
