# Ungula Deployment Guide

## Table of Contents

- [Local Development](#local-development)
- [Configuration Reference](#configuration-reference)
- [Channel Setup](#channel-setup)
- [Production Deployment](#production-deployment)
- [Docker Sandbox](#docker-sandbox)
- [Node Client](#node-client)

---

## Local Development

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 also supported |
| Node.js | 18+ | For the React frontend |
| SQLite | (bundled) | Included with Python |
| Docker | 20+ | Optional, for sandbox |

### Backend Setup

```bash
cd backend

# Create and activate virtualenv
python -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Optional: install browser automation
pip install -e ".[browser]"

# Create minimal config
mkdir -p ~/.ungula
cat > ~/.ungula/config.yaml << 'EOF'
server:
  host: 0.0.0.0
  port: 8001

auth:
  secret_key: dev-only-secret-change-in-prod

llm:
  default_provider: anthropic
  anthropic:
    api_key: sk-ant-...
EOF

# Start the server
python -m ungula.main
# Or with auto-reload:
uvicorn ungula.main:app --host 0.0.0.0 --port 8001 --reload
```

The server starts at `http://localhost:8001`. Swagger UI is at `/docs`.

### Frontend Setup

```bash
cd frontend

npm install
npm run dev
```

The dashboard opens at `http://localhost:3001`. Vite proxies `/api/*` requests to `http://localhost:8001` automatically.

### Running Tests

```bash
cd backend
source .venv/bin/activate

pytest                       # All tests
pytest -x                    # Stop on first failure
pytest --cov=ungula          # Coverage report
pytest tests/test_chat.py    # Single file
```

### Linting & Formatting

```bash
# Backend
cd backend
ruff check .                 # Lint
ruff format .                # Format

# Frontend
cd frontend
npm run lint
```

---

## Configuration Reference

Ungula loads configuration from three sources (highest priority first):

1. **Environment variables** (prefixed `UNGULA_`)
2. **Config file** (`~/.ungula/config.yaml`)
3. **Built-in defaults**

### Directory Structure

```
~/.ungula/
├── config.yaml          # Main configuration
├── workspace/           # Agent workspace files
│   ├── SOUL.md         # Agent persona
│   ├── USER.md         # User context
│   ├── IDENTITY.md     # Agent identity
│   ├── AGENTS.md       # Workspace guide
│   ├── TOOLS.md        # Tool notes
│   ├── MEMORY.md       # Long-term memory
│   ├── HEARTBEAT.md    # Periodic tasks
│   └── BOOT.md         # Startup tasks
├── data/
│   ├── ungula.db       # SQLite database
│   └── embeddings/     # Vector embeddings
├── skills/              # User-installed skills
├── plugins/             # Installed plugins
├── nodes/               # Node data
└── logs/                # Log files
```

### Full config.yaml Reference

```yaml
# Server
server:
  host: "0.0.0.0"               # Bind address
  port: 8001                     # Listen port
  reload: false                  # Auto-reload on code changes
  workers: 1                     # Uvicorn workers
  cors_origins:                  # Allowed CORS origins
    - "http://localhost:3001"
    - "http://localhost:3000"

# Authentication
auth:
  secret_key: "CHANGE-ME-IN-PRODUCTION"   # JWT signing key
  algorithm: "HS256"                       # JWT algorithm
  token_expire_minutes: 1440               # Token lifetime (24h)

# Database
database:
  type: "sqlite"                 # Database type
  path: "ungula.db"              # Path relative to data dir

# LLM Providers
llm:
  default_provider: "openrouter"
  failover_order: []             # Provider failover order (empty = auto)

  openrouter:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  anthropic:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  openai:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  google:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  xai:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  nvidia:
    enabled: true
    api_key: null
    base_url: null
    default_model: null

  ollama:
    enabled: true
    api_key: null
    base_url: "http://localhost:11434"
    default_model: null

  custom_providers: []           # List of custom OpenAI-compatible providers
  # - name: "deepseek"
  #   display_name: "DeepSeek"
  #   api_key: "..."
  #   base_url: "https://api.deepseek.com/v1"
  #   default_model: "deepseek-chat"

# Agent Runtime
agent_runtime:
  max_context_tokens: 200000     # Max context window
  max_history_share: 0.5         # Max fraction of context for history
  reserve_tokens_floor: 20000    # Always reserve for new content
  pruning_enabled: true          # Enable tool result pruning
  soft_trim_ratio: 0.3           # Trigger soft trim at this context fraction
  hard_clear_ratio: 0.5          # Trigger hard clear at this context fraction

# Agents (per-agent configuration)
agents: []
# - id: "researcher"
#   name: "Research Agent"
#   type: "researcher"
#   provider: "anthropic"
#   model: "claude-sonnet-4-20250514"
#   temperature: 0.3
#   max_tokens: 8192
#   max_tool_iterations: 15
#   system_prompt: "You are a research assistant."

# Skills
skills:
  enabled: true
  extra_dirs: []                 # Additional skill directories
  entries: {}                    # Per-skill config overrides
  shell:
    enabled: true
    blocked_commands:
      - "rm -rf /"
      - "sudo rm"
      - "mkfs"
      - "dd if="
      - "> /dev/"
    max_timeout: 30

# Tools
tools:
  brave_search:
    enabled: false
    api_key: null
    max_results: 5
  tavily_search:
    enabled: false
    api_key: null
    max_results: 5
  policy:
    profile: "full"              # minimal, coding, messaging, full
    allowed: []                  # Additional allowed tools
    denied: []                   # Denied tools (overrides allowed)

# Memory
memory:
  enabled: true
  auto_index_workspace: false
  embeddings_provider: "local"   # local or openai
  embeddings_model: null         # Override default model
  embedding_cache_size: 10000    # 0 to disable cache

# Embeddings
embeddings:
  provider: "local"
  model: "all-MiniLM-L6-v2"
  openai_api_key: null

# File Tools
file_tools:
  enabled: true
  max_file_size: 1000000         # 1MB
  denied_extensions:
    - ".env"
    - ".key"
    - ".pem"

# Process Tools
process_tools:
  enabled: true
  max_background: 5
  max_output_size: 50000

# Messaging Channels
messaging:
  discord:
    enabled: false
    token: null
    dm_enabled: true
    dm_policy: "pairing"         # open, pairing, allowlist
    dm_allowlist: []
    guild_policy: "allowlist"    # open, allowlist, disabled
    guild_allowlist: {}
    mention_required: true
    max_response_length: 2000

  telegram:
    enabled: false
    token: null
    allowed_users: []            # Empty = all users
    allowed_chats: []            # Empty = all chats

  slack:
    enabled: false
    bot_token: null              # xoxb-...
    app_token: null              # xapp-...

  signal:
    enabled: false
    account: null                # Phone number +1234567890
    cli_path: "signal-cli"
    allowed_users: []
    allowed_groups: []

  imessage:
    enabled: false
    cli_path: "imsg"
    dm_policy: "pairing"
    dm_allowlist: []

# Node System (companion devices)
node_system:
  enabled: true
  max_nodes: 10
  pairing_ttl: 300               # Pairing request TTL (seconds)
  heartbeat_interval: 30
  heartbeat_timeout: 90
  command_timeout: 60
  allow_commands: []
  deny_commands: []

# Webhooks
webhooks:
  enabled: true
  max_webhooks: 50
  max_payload_size: 1000000
  event_retention_days: 7

# Browser Automation
browser:
  enabled: false
  headless: true
  timeout: 30
  max_tabs: 5

# Plugins
plugins:
  enabled: true
  plugin_dirs: []

# Docker Sandbox
sandbox:
  enabled: false
  image: "python:3.11-slim"
  mount_mode: "readonly"         # readonly, readwrite, none
  working_dir: "/workspace"
  memory_limit: "256m"
  cpu_limit: 1.0
  timeout: 30
  network_enabled: false
  auto_cleanup: true
  read_only_root: true
  cap_drop: ["ALL"]
  no_new_privileges: true
  pids_limit: 100

# Redis (for future queue support)
redis:
  host: "localhost"
  port: 6379
  db: 0
  password: null
```

### Environment Variables

All environment variables use the `UNGULA_` prefix.

| Variable | Config Path | Description |
|---|---|---|
| `UNGULA_HOME` | — | Config directory (default: `~/.ungula`) |
| `UNGULA_AUTH_SECRET_KEY` | `auth.secret_key` | JWT signing secret |
| `UNGULA_SERVER_HOST` | `server.host` | Server bind address |
| `UNGULA_SERVER_PORT` | `server.port` | Server port |
| `UNGULA_OPENROUTER_API_KEY` | `llm.openrouter.api_key` | OpenRouter API key |
| `UNGULA_ANTHROPIC_API_KEY` | `llm.anthropic.api_key` | Anthropic API key |
| `UNGULA_OPENAI_API_KEY` | `llm.openai.api_key` | OpenAI API key |
| `UNGULA_GOOGLE_API_KEY` | `llm.google.api_key` | Google AI API key |
| `UNGULA_XAI_API_KEY` | `llm.xai.api_key` | xAI API key |
| `UNGULA_NVIDIA_API_KEY` | `llm.nvidia.api_key` | NVIDIA NIM API key |
| `UNGULA_DISCORD_TOKEN` | `messaging.discord.token` | Discord bot token |
| `UNGULA_REDIS_HOST` | `redis.host` | Redis host |
| `UNGULA_REDIS_PORT` | `redis.port` | Redis port |
| `UNGULA_REDIS_PASSWORD` | `redis.password` | Redis password |

---

## Channel Setup

### Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Under **Bot**, create a bot and copy the token.
3. Enable **Message Content Intent** under Privileged Gateway Intents.
4. Generate an invite URL under **OAuth2 > URL Generator** with scopes: `bot`, `applications.commands`. Permissions: Send Messages, Read Message History, Read Messages/View Channels.
5. Invite the bot to your server.
6. Configure Ungula:

```yaml
messaging:
  discord:
    enabled: true
    token: "YOUR_BOT_TOKEN"
    dm_policy: "allowlist"          # or "open" / "pairing"
    dm_allowlist:
      - "YOUR_DISCORD_USER_ID"
    guild_policy: "allowlist"
    guild_allowlist:
      "YOUR_GUILD_ID":
        channels: ["CHANNEL_ID"]
    mention_required: true
```

Or via environment variable:
```bash
export UNGULA_DISCORD_TOKEN="YOUR_BOT_TOKEN"
```

### Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot with `/newbot`.
2. Copy the token.
3. Configure:

```yaml
messaging:
  telegram:
    enabled: true
    token: "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    allowed_users: ["YOUR_TELEGRAM_USER_ID"]     # Empty = allow all
    allowed_chats: []
```

### Slack App

1. Create a new app at [api.slack.com/apps](https://api.slack.com/apps).
2. Enable **Socket Mode** and generate an app-level token (starts with `xapp-`).
3. Under **OAuth & Permissions**, add scopes: `chat:write`, `channels:history`, `channels:read`, `im:history`, `im:read`, `im:write`.
4. Install to your workspace and copy the bot token (starts with `xoxb-`).
5. Configure:

```yaml
messaging:
  slack:
    enabled: true
    bot_token: "xoxb-..."
    app_token: "xapp-..."
```

### Signal

Requires [signal-cli](https://github.com/AsamK/signal-cli) installed and registered.

1. Install signal-cli and register or link an account.
2. Configure:

```yaml
messaging:
  signal:
    enabled: true
    account: "+1234567890"
    cli_path: "/usr/local/bin/signal-cli"    # Or just "signal-cli" if on PATH
    allowed_users: ["+1234567890"]
    allowed_groups: []
```

### iMessage (macOS only)

Requires the `imsg` CLI tool and macOS with Messages.app configured.

```yaml
messaging:
  imessage:
    enabled: true
    cli_path: "imsg"
    dm_policy: "allowlist"
    dm_allowlist:
      - "+1234567890"
      - "user@icloud.com"
```

---

## Production Deployment

### Reverse Proxy (nginx)

Place nginx in front of Ungula to handle TLS, WebSocket upgrades, and static assets.

```nginx
server {
    listen 443 ssl;
    server_name ungula.example.com;

    ssl_certificate /etc/letsencrypt/live/ungula.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ungula.example.com/privkey.pem;

    # API and WebSocket
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket endpoints
    location /ws {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # SSE endpoints need buffering disabled
    location /api/channels/events {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
    }

    location /api/chat/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
    }

    # Frontend (build and serve statically)
    location / {
        root /opt/ungula/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

Build the frontend for production:

```bash
cd frontend
npm run build
# Output in frontend/dist/
```

### systemd Service (Linux)

Create `/etc/systemd/system/ungula.service`:

```ini
[Unit]
Description=Ungula AI Agent Platform
After=network.target

[Service]
Type=simple
User=ungula
Group=ungula
WorkingDirectory=/opt/ungula/backend
Environment=UNGULA_HOME=/opt/ungula/config
Environment=UNGULA_AUTH_SECRET_KEY=your-production-secret
ExecStart=/opt/ungula/backend/.venv/bin/python -m ungula.main
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ungula/config
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ungula
sudo systemctl start ungula
sudo journalctl -u ungula -f
```

### launchd Service (macOS)

Create `~/Library/LaunchAgents/com.ungula.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ungula.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/backend/.venv/bin/python</string>
        <string>-m</string>
        <string>ungula.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/backend</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ungula.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ungula.stderr.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.ungula.agent.plist
launchctl start com.ungula.agent
```

### Security Checklist

Before exposing Ungula to the network:

- [ ] Change `auth.secret_key` from the default (`CHANGE-ME-IN-PRODUCTION`)
- [ ] Set `UNGULA_AUTH_SECRET_KEY` via environment variable, not config file
- [ ] Restrict `~/.ungula/` permissions: `chmod 700 ~/.ungula && chmod 600 ~/.ungula/config.yaml`
- [ ] Use TLS (HTTPS) via reverse proxy
- [ ] Restrict `cors_origins` to your actual frontend domain
- [ ] Review `skills.shell.blocked_commands` — the default list is minimal
- [ ] Consider setting `tools.policy.profile` to `coding` or `minimal` instead of `full`
- [ ] Enable `sandbox.enabled: true` for Docker-isolated tool execution
- [ ] Set `sandbox.network_enabled: false` (default) to prevent network access from sandbox
- [ ] Review channel policies (`dm_policy`, `guild_policy`) — avoid `open` in production
- [ ] Set `file_tools.denied_extensions` to block sensitive file types
- [ ] Run `POST /api/security/audit` periodically and review findings
- [ ] Restrict `node_system.deny_commands` for any dangerous commands

---

## Docker Sandbox

The Docker sandbox runs tool execution (shell commands, code) in isolated containers.

### Prerequisites

- Docker Engine 20+ installed and running
- The user running Ungula must have permission to use Docker (docker group or rootless mode)

### Enable

```yaml
sandbox:
  enabled: true
  image: "python:3.11-slim"
  memory_limit: "256m"
  cpu_limit: 1.0
  timeout: 30
  network_enabled: false
  mount_mode: "readonly"
```

### Mount Modes

| Mode | Description |
|---|---|
| `readonly` | Workspace mounted read-only inside container |
| `readwrite` | Workspace mounted read-write (use with caution) |
| `none` | No workspace mount |

### Security Hardening Options

The sandbox drops all Linux capabilities by default and prevents privilege escalation:

```yaml
sandbox:
  read_only_root: true           # Read-only root filesystem
  cap_drop: ["ALL"]              # Drop all capabilities
  no_new_privileges: true        # No privilege escalation
  pids_limit: 100                # Prevent fork bombs
  tmpfs_mounts:                  # Writable temp directories
    - "/tmp"
    - "/var/tmp"
    - "/run"
  user: "1000:1000"              # Run as non-root
  seccomp_profile: null          # Custom seccomp profile (JSON path)
  dns: []                        # Custom DNS servers
```

### Custom Images

For specialized tool execution, build a custom image:

```dockerfile
FROM python:3.11-slim
RUN pip install numpy pandas matplotlib
```

```yaml
sandbox:
  image: "my-ungula-sandbox:latest"
```

---

## Node Client

The node client (`ungula-node`) turns any Python-capable device into a companion node that Ungula can dispatch commands to.

### Install

```bash
cd node-client
pip install -e .
# Or from the device directly:
pip install ungula-node
```

### Pairing Flow

**Step 1:** From the node device, request pairing:

```bash
ungula-node pair --gateway ws://YOUR_SERVER:8001/ws/node --name "My MacBook"
```

**Step 2:** On the server (via API or dashboard), approve the request:

```bash
# List pending requests
curl http://YOUR_SERVER:8001/api/nodes/pending

# Approve
curl -X POST http://YOUR_SERVER:8001/api/nodes/NODE_ID/approve
```

The approve response includes a pairing token.

**Step 3:** Connect with the token:

```bash
ungula-node connect \
  --gateway ws://YOUR_SERVER:8001/ws/node \
  --token PAIRING_TOKEN
```

### CLI Commands

| Command | Description |
|---|---|
| `ungula-node pair -g URL -n NAME` | Initiate pairing |
| `ungula-node connect -g URL -t TOKEN` | Connect with token |
| `ungula-node status -g URL` | Show nodes and pending requests |
| `ungula-node approve -g URL NODE_ID` | Approve a pairing request |
| `ungula-node reject -g URL NODE_ID` | Reject a pairing request |
| `ungula-node capabilities` | List registered capabilities |

### Options

```
--gateway, -g     Gateway URL (ws:// for connect/pair, http:// for status/approve/reject)
--token, -t       Pairing token (for connect)
--name, -n        Node display name (for pair)
--platform, -p    Platform override (auto-detected if omitted)
--heartbeat       Heartbeat interval in seconds (default: 30)
--verbose, -v     Enable debug logging
```

### Invoking Commands

Once connected, the server can invoke commands on the node via the API:

```bash
curl -X POST http://localhost:8001/api/nodes/NODE_ID/invoke \
  -H "Content-Type: application/json" \
  -d '{"command": "shell", "args": {"cmd": "hostname"}}'
```

The agent can also invoke node commands directly via the `node_invoke` tool during conversations.
