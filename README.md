# agentic-coding-bootstrap

Bootstrap script for agentic coding tools (Codex CLI + MCP + Cursor MCP config).

One-line install options:

- `git clone https://github.com/n-patiphon/agentic-coding-bootstrap.git && cd agentic-coding-bootstrap && ./bootstrap-agentic-coding.sh`
- `curl -fsSL https://raw.githubusercontent.com/n-patiphon/agentic-coding-bootstrap/main/bootstrap-agentic-coding.sh | bash -s --` (requires `curl`; downloads `assets/*` automatically)

Usage:

- `./bootstrap-agentic-coding.sh --help`
- `./bootstrap-agentic-coding.sh`

## Slack notifications (Codex CLI)

The default `assets/codex-config.default.toml` enables `notify` and installs a small notifier script.

Preferred (threaded, grouped by Codex `session_id`, and broadcast in-channel):

- Slack Web API: `export SLACK_BOT_TOKEN='xoxb-...'` and `export SLACK_CHANNEL='C0123456789'`

Fallbacks:

- Incoming webhook (unthreaded): `export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'`
- Desktop notification: `notify-send` (if installed)

Message format:

- First message in a session thread: `Task summary (<dir>)` + the assistant message
- Replies: assistant message only (to keep the channel/thread less cluttered)
