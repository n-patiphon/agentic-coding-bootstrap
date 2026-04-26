# agentic-coding-bootstrap

Bootstrap script for agentic coding tools.

One-line install options:

- `git clone https://github.com/n-patiphon/agentic-coding-bootstrap.git && cd agentic-coding-bootstrap && ./bootstrap-agentic-coding.sh`
- `curl -fsSL https://raw.githubusercontent.com/n-patiphon/agentic-coding-bootstrap/main/bootstrap-agentic-coding.sh | bash -s --`

Usage:

- `./bootstrap-agentic-coding.sh --help`
- `./bootstrap-agentic-coding.sh`

## What it installs

- Node.js with `npm` and `npx` when needed
- `uv` / `uvx`
- Codex CLI
- OpenCode CLI

This repo does not manage any personal configuration. It intentionally does **not** write:

- `~/.codex/config.toml`
- `~/.config/opencode/opencode.json`
- MCP config
- notifier scripts
- provider/model settings

## Next step after install

Apply your private config repo after the tools are installed.

Example:

```bash
git clone <private-config-repo> ~/local_work/misc_ws/agentic_coding_configs
cd ~/local_work/misc_ws/agentic_coding_configs
python3 scripts/codex_sync.py --all --apply
python3 scripts/opencode_sync.py --all --apply
```

References:

- Codex CLI: https://developers.openai.com/codex/
- OpenCode install docs: https://opencode.ai/en/docs
