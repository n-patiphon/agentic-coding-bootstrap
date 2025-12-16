#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<EOF
Installs Codex CLI prerequisites and (optionally) writes a default MCP config.

Usage:
  ${SCRIPT_NAME} [--dry-run] [--no-install] [--no-config]

What it does:
  - Ensures Node.js (with npm+npx), uv/uvx, and Codex CLI are installed.
  - Copies a default config template to ~/.codex/config.toml if missing.

Notes:
  - On Debian/Ubuntu, Node.js is installed via the NodeSource apt repo (NODE_MAJOR, default: 20).
  - If Codex is installed to a user prefix, you'll need \$HOME/.local/bin on your PATH.

Options:
  --no-install  Don't install missing tools (error if missing).
  --no-config   Don't write ~/.codex/config.toml.
  --dry-run     Print what would happen.
  -h, --help    Show this help.

Env:
  NODE_MAJOR=20   Node.js major version to install on Debian/Ubuntu.
  FS_ALLOWED_DIR=/workspaces  Override the filesystem MCP allowed directory.
EOF
}

log() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

INSTALL=true
WRITE_CONFIG=true
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install) INSTALL=false ;;
    --no-config) WRITE_CONFIG=false ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
  shift
done

run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN: $*"
    return 0
  fi
  "$@"
}

LOCAL_BIN="${HOME}/.local/bin"
# Allow the script itself to see user installs (even if the parent shell doesn't).
export PATH="${LOCAL_BIN}:${PATH}"

run_root() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN (root): $*"
    return 0
  fi
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return 0
  fi
  have sudo || die "Need sudo (or run as root) to install system packages."
  sudo "$@"
}

node_major() { node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0; }

is_nvm_bin() {
  local p="$1"
  [[ -n "${p}" ]] && [[ "${p}" == "${HOME}/.nvm/"* ]]
}

maybe_link_usr_local() {
  # If a tool ends up in ~/.local/bin, symlink it into /usr/local/bin when possible
  # so it works even if the parent shell doesn't have ~/.local/bin on PATH.
  local name="$1"
  local src="$2"
  [[ -x "${src}" ]] || return 0
  [[ -d /usr/local/bin ]] || return 0

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN: would symlink ${src} -> /usr/local/bin/${name}"
    return 0
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    ln -sf "${src}" "/usr/local/bin/${name}"
    return 0
  fi
  if have sudo; then
    sudo ln -sf "${src}" "/usr/local/bin/${name}" >/dev/null 2>&1 || true
  fi
}

install_node_debian() {
  local major="${NODE_MAJOR:-20}"
  log "Installing Node.js ${major}.x (Debian/Ubuntu via NodeSource)..."
  run_root apt-get update
  run_root apt-get install -y --no-install-recommends ca-certificates curl gnupg
  run_root install -d -m 0755 /etc/apt/keyrings
  run_root bash -lc "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg"
  run_root bash -lc "echo \"deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${major}.x nodistro main\" > /etc/apt/sources.list.d/nodesource.list"
  run_root apt-get update
  run_root apt-get install -y --no-install-recommends nodejs
}

ensure_node() {
  local required_major="${NODE_MAJOR_REQUIRED:-18}"
  if have node && have npm && have npx; then
    local installed
    installed="$(node_major)"
    local node_path
    node_path="$(command -v node 2>/dev/null || true)"

    # If Node comes from nvm, it may disappear in new shells unless nvm is sourced.
    if [[ "${installed}" -ge "${required_major}" ]] && ! is_nvm_bin "${node_path}"; then
      return 0
    fi
    if is_nvm_bin "${node_path}"; then
      warn "Found Node.js v${installed} from nvm (${node_path})."
      if [[ "${INSTALL}" != "true" ]]; then
        warn "Skipping system Node install (--no-install); note: npx may not be available in new shells unless nvm is sourced."
        return 0
      fi
      warn "Installing system Node so npx works without shell init."
    else
      warn "Found Node.js v${installed}, but need >= ${required_major}."
    fi
  fi

  [[ "${INSTALL}" == "true" ]] || die "Missing/old node/npm/npx (re-run without --no-install)."

  if have apt-get; then
    install_node_debian
    return 0
  fi

  die "Don't know how to install Node.js on this system (no apt-get). Install Node.js >= ${required_major} manually."
}

install_uv() {
  have curl || die "curl is required to install uv."
  log "Installing uv (uv + uvx)..."
  run bash -lc "curl -LsSf https://astral.sh/uv/install.sh | sh"
  maybe_link_usr_local uv "${LOCAL_BIN}/uv"
  maybe_link_usr_local uvx "${LOCAL_BIN}/uvx"
}

install_codex() {
  log "Installing Codex CLI (@openai/codex)..."
  if [[ "$(id -u)" -eq 0 ]]; then
    run npm install -g @openai/codex
    return 0
  fi
  if have sudo; then
    # Prefer system-global install so `codex` is immediately on PATH.
    if run_root npm install -g @openai/codex; then
      return 0
    fi
  fi
  run npm install -g --prefix "${HOME}/.local" @openai/codex
  maybe_link_usr_local codex "${LOCAL_BIN}/codex"
}

CODEX_DIR="${HOME}/.codex"
CONFIG_PATH="${CODEX_DIR}/config.toml"
TEMPLATE_PATH="${SCRIPT_DIR}/assets/codex-config.default.toml"

ensure_node

if ! have uvx; then
  [[ "${INSTALL}" == "true" ]] || die "Missing uvx (re-run without --no-install)."
  install_uv
fi

if ! have codex; then
  [[ "${INSTALL}" == "true" ]] || die "Missing codex (re-run without --no-install)."
  have npm || die "npm is required to install Codex CLI."
  install_codex
else
  codex_path="$(command -v codex 2>/dev/null || true)"
  if is_nvm_bin "${codex_path}" && [[ "${INSTALL}" == "true" ]]; then
    # Fix common "installed but not found in new shells" issue from nvm-based installs.
    warn "Found codex from nvm (${codex_path}); also installing a system-global codex."
    install_codex || true
  fi
fi

if [[ "${WRITE_CONFIG}" == "true" ]] && [[ ! -e "${CONFIG_PATH}" ]]; then
  [[ -f "${TEMPLATE_PATH}" ]] || die "Missing template: ${TEMPLATE_PATH}"
  local_allowed_dir="${FS_ALLOWED_DIR:-}"
  if [[ -z "${local_allowed_dir}" ]]; then
    if [[ -d /workspaces ]]; then
      local_allowed_dir="/workspaces"
    else
      local_allowed_dir="$(pwd)"
    fi
  fi
  [[ -d "${local_allowed_dir}" ]] || die "FS_ALLOWED_DIR does not exist: ${local_allowed_dir}"

  log "Writing default Codex config: ${CONFIG_PATH}"
  run mkdir -p "${CODEX_DIR}"
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY_RUN: would substitute __FS_ALLOWED_DIR__ => ${local_allowed_dir}"
  else
    umask 077
    tmp="${CONFIG_PATH}.tmp.$$"
    sed "s|__FS_ALLOWED_DIR__|${local_allowed_dir}|g" "${TEMPLATE_PATH}" > "${tmp}"
    chmod 600 "${tmp}"
    mv "${tmp}" "${CONFIG_PATH}"
  fi
elif [[ "${WRITE_CONFIG}" == "true" ]]; then
  log "Config already exists, not overwriting: ${CONFIG_PATH}"
fi

for cmd in node npm npx uvx codex; do
  have "${cmd}" || die "Required command not found on PATH: ${cmd}"
done

if ! have git; then
  warn "git not found; `uvx --from git+...` (serena MCP) will need git installed."
fi

log "Bootstrap complete."
log "  codex: $(command -v codex) ($(codex --version 2>/dev/null || echo 'unknown'))"
log "  npx:   $(command -v npx)"
log "  uvx:   $(command -v uvx)"
