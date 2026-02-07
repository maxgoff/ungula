# Ungula API Reference

Base URL: `http://localhost:8001`

All endpoints are under `/api/` unless noted. Authentication uses JWT Bearer tokens where indicated. Rate limiting defaults to 60 requests/minute per IP.

Interactive Swagger docs are available at `/docs`.

---

## Table of Contents

- [Authentication](#authentication)
- [Configuration](#configuration)
- [Conversations](#conversations)
- [Chat](#chat)
- [Channels & Inbox](#channels--inbox)
- [Skills & Tools](#skills--tools)
- [Memory](#memory)
- [Agents](#agents)
- [Runtime](#runtime)
- [Subagents](#subagents)
- [Nodes](#nodes)
- [Pairing](#pairing)
- [Webhooks](#webhooks)
- [Plugins](#plugins)
- [Cron & Scheduling](#cron--scheduling)
- [Security](#security)
- [Usage & Monitoring](#usage--monitoring)
- [WebSocket Protocol](#websocket-protocol)
- [Health & Info](#health--info)

---

## Authentication

Prefix: `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | No | Register a new user (5/min rate limit) |
| POST | `/api/auth/login` | No | Login and get JWT token (10/min rate limit) |
| GET | `/api/auth/me` | Yes | Get current user profile |

### POST /api/auth/register

Create a new user account and receive a JWT token.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "minimum8chars",
  "name": "Display Name"
}
```

**Response (201):**
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer"
}
```

**Errors:** `409` if email already registered.

```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass", "name": "Alice"}'
```

### POST /api/auth/login

Authenticate with email/password and receive a JWT token.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepass"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer"
}
```

**Errors:** `401` invalid credentials, `403` account deactivated.

### GET /api/auth/me

Returns the authenticated user's profile.

**Response (200):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Alice",
  "is_active": true,
  "created_at": "2026-01-15T10:30:00"
}
```

**Using the token:**
```bash
curl http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Configuration

Prefix: `/api/config`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/config/` | No | Get current configuration |
| POST | `/api/config/reload` | Yes | Reload config from disk |
| GET | `/api/config/workspace` | No | List workspace files |
| GET | `/api/config/workspace/{filename}` | No | Get workspace file content |
| PUT | `/api/config/workspace/{filename}` | Yes | Update workspace file |
| POST | `/api/config/initialize-workspace` | Yes | Initialize workspace from templates |
| GET | `/api/config/providers` | No | List LLM providers and status |
| PUT | `/api/config/providers/{name}` | Yes | Update a provider's config |
| POST | `/api/config/providers` | Yes | Add a custom provider |
| DELETE | `/api/config/providers/{name}` | Yes | Remove a custom provider |
| PUT | `/api/config/failover-order` | Yes | Update provider failover order |

### GET /api/config/providers

List all configured LLM providers with their status.

**Response (200):**
```json
{
  "providers": [
    {
      "name": "anthropic",
      "enabled": true,
      "has_key": true,
      "default_model": "claude-sonnet-4-20250514",
      "base_url": null
    }
  ],
  "default_provider": "anthropic"
}
```

### PUT /api/config/workspace/{filename}

Update a workspace file.

**Request:**
```json
{
  "content": "# Updated content\n\nNew persona instructions."
}
```

```bash
curl -X PUT http://localhost:8001/api/config/workspace/SOUL.md \
  -H "Content-Type: application/json" \
  -d '{"content": "# My Agent\nYou are a helpful assistant."}'
```

---

## Conversations

Prefix: `/api/conversations`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/conversations/` | Yes | Create a conversation |
| GET | `/api/conversations/` | Yes | List user's conversations |
| GET | `/api/conversations/{id}` | Yes | Get conversation with messages |
| DELETE | `/api/conversations/{id}` | Yes | Delete a conversation |
| POST | `/api/conversations/{id}/messages` | Yes | Add a message |
| GET | `/api/conversations/{id}/messages` | Yes | List messages |

### POST /api/conversations/

**Request:**
```json
{
  "title": "My Conversation",
  "metadata": {}
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "title": "My Conversation",
  "user_id": "uuid",
  "created_at": "2026-01-15T10:30:00",
  "updated_at": "2026-01-15T10:30:00",
  "metadata": {}
}
```

### POST /api/conversations/{id}/messages

Add a message to a conversation (does not trigger agent response — use `/api/chat/` for that).

**Request:**
```json
{
  "role": "user",
  "content": "Hello!",
  "metadata": {}
}
```

```bash
curl -X POST http://localhost:8001/api/conversations/CONV_ID/messages \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "user", "content": "Hello!"}'
```

---

## Chat

Prefix: `/api/chat`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/chat/{conversation_id}` | Yes | Send message, get response |
| POST | `/api/chat/{conversation_id}/stream` | Yes | Send message, stream response (SSE) |

### POST /api/chat/{conversation_id}

Send a user message and receive the agent's response (non-streaming).

**Request:**
```json
{
  "content": "What can you do?",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "temperature": 0.7,
  "max_tokens": 4096,
  "provider_params": {},
  "agent_id": "optional-agent-id"
}
```

Only `content` is required. All other fields are optional overrides.

**Response (200):**
```json
{
  "message_id": "uuid",
  "content": "I can help you with...",
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",
  "finish_reason": "end_turn"
}
```

```bash
curl -X POST http://localhost:8001/api/chat/CONV_ID \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Summarize the news today"}'
```

### POST /api/chat/{conversation_id}/stream

Stream the agent's response as Server-Sent Events (SSE).

**Request:** Same as non-streaming chat.

**SSE Events:**

| Event | Data | Description |
|-------|------|-------------|
| `start` | `{"message_id": "uuid"}` | Response started |
| `chunk` | `{"content": "partial text"}` | Text content chunk |
| `tool_call` | `{"name": "...", "args": {...}}` | Tool invocation |
| `tool_result` | `{"name": "...", "result": "..."}` | Tool execution result |
| `done` | `{"message_id": "...", "finish_reason": "...", "model": "...", "provider": "..."}` | Response complete |
| `error` | `{"code": "...", "message": "...", "retryable": bool}` | Error occurred |

```bash
curl -N -X POST http://localhost:8001/api/chat/CONV_ID/stream \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Write a haiku"}'
```

---

## Channels & Inbox

Prefix: `/api/channels`

### Channel Management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/channels` | No | List all channels and their status |
| GET | `/api/channels/{channel}/health` | No | Health check for a channel |
| POST | `/api/channels/{channel}/start` | Yes | Start a channel |
| POST | `/api/channels/{channel}/stop` | Yes | Stop a channel |
| GET | `/api/channels/events` | No | SSE stream of channel events |

### Inbox

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/channels/inbox` | No | List inbox messages (paginated) |
| GET | `/api/channels/inbox/{message_id}` | No | Get a single inbox message |
| POST | `/api/channels/inbox/{message_id}/read` | No | Mark message as read |
| POST | `/api/channels/inbox/read` | No | Bulk mark messages as read |
| POST | `/api/channels/inbox/reply` | Yes | Reply to a session |

### Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/channels/sessions` | No | List messaging sessions |
| GET | `/api/channels/sessions/{session_id}` | No | Get session details with messages |
| DELETE | `/api/channels/sessions/{session_id}` | No | Delete a session |

### GET /api/channels

```json
{
  "channels": [
    {
      "name": "discord",
      "running": true,
      "enabled": true,
      "healthy": true,
      "message_count": 42
    }
  ]
}
```

### POST /api/channels/inbox/reply

Send a reply back through a messaging channel.

**Request:**
```json
{
  "session_id": "discord:user:123456",
  "content": "Hello from the API!"
}
```

### GET /api/channels/events

Server-Sent Events stream for real-time channel activity (new messages, status changes).

```bash
curl -N http://localhost:8001/api/channels/events
```

---

## Skills & Tools

Prefix: `/api/skills`

### Skill Management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/skills/` | No | List all loaded skills |
| GET | `/api/skills/tools` | No | List all registered tools |
| GET | `/api/skills/{name}` | No | Get skill details |
| POST | `/api/skills/{name}/enable` | Yes | Enable a skill |
| POST | `/api/skills/{name}/disable` | Yes | Disable a skill |
| POST | `/api/skills/{name}/scan` | No | Security scan an installed skill |
| DELETE | `/api/skills/{name}` | Yes | Uninstall a skill |
| POST | `/api/skills/reload` | Yes | Reload all skills |

### ClawHub Marketplace

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/skills/clawhub/search` | No | Search ClawHub for skills |
| GET | `/api/skills/clawhub/{slug}` | No | Get ClawHub skill details |
| POST | `/api/skills/clawhub/check-compatibility` | No | Check skill compatibility |
| POST | `/api/skills/clawhub/check-security` | No | Security scan before install |
| POST | `/api/skills/clawhub/install` | Yes | Install a skill from ClawHub |

### GET /api/skills/

```json
{
  "skills": [
    {
      "name": "web_search",
      "version": "1.0.0",
      "description": "Search the web using Brave or Tavily",
      "enabled": true,
      "tools": ["web_search"]
    }
  ]
}
```

### GET /api/skills/tools

```json
{
  "tools": [
    {
      "name": "web_search",
      "description": "Search the web",
      "parameters": { "type": "object", "properties": { "query": { "type": "string" } } },
      "skill": "web_search"
    }
  ]
}
```

### POST /api/skills/clawhub/install

```json
{
  "slug": "my-skill"
}
```

```bash
curl -X POST http://localhost:8001/api/skills/clawhub/install \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slug": "my-skill"}'
```

---

## Memory

Prefix: `/api/memory`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/memory/search` | Yes | Semantic search over memory |
| POST | `/api/memory/add` | Yes | Add a memory entry |
| DELETE | `/api/memory/{memory_id}` | Yes | Delete a memory entry |
| POST | `/api/memory/sync` | Yes | Sync memory from workspace files |
| POST | `/api/memory/index` | Yes | Index a document into memory |
| GET | `/api/memory/status` | Yes | Get memory system status |

### POST /api/memory/search

Semantic search across stored memories.

**Request:**
```json
{
  "query": "how to deploy",
  "top_k": 5,
  "threshold": 0.7
}
```

**Response (200):**
```json
{
  "results": [
    {
      "id": "uuid",
      "content": "To deploy Ungula...",
      "score": 0.92,
      "metadata": { "source": "MEMORY.md" }
    }
  ]
}
```

### POST /api/memory/add

**Request:**
```json
{
  "content": "The user prefers dark mode.",
  "metadata": { "category": "preferences" }
}
```

### POST /api/memory/index

Index a document (file content) into the memory system.

**Request:**
```json
{
  "content": "Document text here...",
  "source": "notes.md",
  "chunk_size": 500
}
```

---

## Agents

Prefix: `/api/agents`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/agents/` | No | List all configured agents |
| GET | `/api/agents/{agent_id}` | No | Get agent configuration |
| POST | `/api/agents/` | Yes | Create a new agent |
| PUT | `/api/agents/{agent_id}` | Yes | Update agent configuration |
| DELETE | `/api/agents/{agent_id}` | Yes | Delete an agent |

### POST /api/agents/

**Request:**
```json
{
  "id": "researcher",
  "name": "Research Agent",
  "type": "researcher",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "temperature": 0.3,
  "max_tokens": 8192,
  "max_tool_iterations": 15,
  "system_prompt": "You are a research assistant.",
  "default_provider_params": {}
}
```

**Response (201):**
```json
{
  "id": "researcher",
  "name": "Research Agent",
  "type": "researcher",
  "enabled": true,
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "temperature": 0.3,
  "max_tokens": 8192,
  "max_tool_iterations": 15
}
```

---

## Runtime

Prefix: `/api/runtime`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/runtime/` | No | Get current runtime configuration |
| PUT | `/api/runtime/` | Yes | Update runtime configuration |
| PUT | `/api/runtime/default-provider` | Yes | Set the default LLM provider |
| PUT | `/api/runtime/default-model` | Yes | Set the default model |

### GET /api/runtime/

```json
{
  "default_provider": "anthropic",
  "default_model": null,
  "max_context_tokens": 200000,
  "max_history_share": 0.5,
  "pruning_enabled": true
}
```

### PUT /api/runtime/default-provider

**Request:**
```json
{
  "provider": "openai"
}
```

---

## Subagents

Prefix: `/api/subagents`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/subagents/spawn` | Yes | Spawn a subagent |
| GET | `/api/subagents/` | Yes | List active subagents |
| GET | `/api/subagents/{session_id}` | Yes | Get subagent status |
| POST | `/api/subagents/{session_id}/cancel` | Yes | Cancel a running subagent |
| GET | `/api/subagents/{session_id}/result` | Yes | Get subagent result |

### POST /api/subagents/spawn

**Request:**
```json
{
  "task": "Research quantum computing papers from 2025",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514"
}
```

**Response (200):**
```json
{
  "session_id": "uuid",
  "status": "running"
}
```

---

## Nodes

Prefix: `/api/nodes`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/nodes/` | No | List all connected nodes |
| POST | `/api/nodes/` | No | Initiate pairing (server-side) |
| GET | `/api/nodes/pending` | No | List pending pairing requests |
| GET | `/api/nodes/exec-approvals/pending` | No | List pending execution approvals |
| POST | `/api/nodes/exec-approvals/{id}/resolve` | No | Approve/deny an execution request |
| GET | `/api/nodes/{node_id}` | No | Get node details |
| DELETE | `/api/nodes/{node_id}` | No | Remove a node |
| POST | `/api/nodes/{node_id}/approve` | No | Approve a pairing request |
| POST | `/api/nodes/{node_id}/reject` | No | Reject a pairing request |
| POST | `/api/nodes/{node_id}/invoke` | No | Invoke a command on a node |
| GET | `/api/nodes/{node_id}/logs` | No | Get command execution logs |

### GET /api/nodes/

```json
{
  "nodes": [
    {
      "id": "node-abc123",
      "name": "MacBook Pro",
      "platform": "macos",
      "status": "online",
      "capabilities": ["shell", "file_read", "file_write"],
      "last_heartbeat": "2026-01-15T10:30:00"
    }
  ]
}
```

### POST /api/nodes/{node_id}/invoke

Execute a command on a connected node.

**Request:**
```json
{
  "command": "shell",
  "args": { "cmd": "uname -a" }
}
```

**Response (200):**
```json
{
  "result": "Darwin MacBook.local 24.6.0 ...",
  "exit_code": 0,
  "duration_ms": 45
}
```

---

## Pairing

Prefix: `/api/pairing`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/pairing/verify` | Yes | Verify a pairing code |
| GET | `/api/pairing/pending` | Yes | List pending pairing requests |
| DELETE | `/api/pairing/{code}` | Yes | Revoke a pairing code |

---

## Webhooks

Prefix: `/api/webhooks`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/webhooks/` | No | Create a webhook |
| GET | `/api/webhooks/` | No | List all webhooks |
| GET | `/api/webhooks/{webhook_id}` | No | Get webhook details |
| PUT | `/api/webhooks/{webhook_id}` | No | Update a webhook |
| DELETE | `/api/webhooks/{webhook_id}` | No | Delete a webhook |
| GET | `/api/webhooks/{webhook_id}/events` | No | Get webhook event history |
| POST | `/api/webhooks/receive/{slug}` | No | Receive an inbound webhook |
| POST | `/api/webhooks/{webhook_id}/test` | No | Send a test event |

### POST /api/webhooks/

**Request:**
```json
{
  "name": "GitHub Push",
  "slug": "github-push",
  "secret": "optional-hmac-secret",
  "template": "New push to {{ payload.repository.name }} by {{ payload.sender.login }}",
  "conversation_id": "uuid"
}
```

### POST /api/webhooks/receive/{slug}

This is the inbound endpoint for external services. When an external service sends a POST to this URL, Ungula verifies the signature (if configured), renders the template, and routes the message to the agent.

```bash
# Example: GitHub webhook callback URL
# https://your-domain.com/api/webhooks/receive/github-push
```

### POST /api/webhooks/{webhook_id}/test

**Request:**
```json
{
  "payload": { "key": "test value" }
}
```

---

## Plugins

Prefix: `/api/plugins`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/plugins/` | No | List discovered plugins |
| GET | `/api/plugins/{name}` | No | Get plugin details |
| POST | `/api/plugins/{name}/enable` | No | Enable a plugin |
| POST | `/api/plugins/{name}/disable` | No | Disable a plugin |
| POST | `/api/plugins/install` | No | Install a plugin |
| DELETE | `/api/plugins/{name}` | No | Uninstall a plugin |
| POST | `/api/plugins/reload` | No | Re-scan plugin directories |

### POST /api/plugins/install

**Request:**
```json
{
  "source": "https://github.com/user/ungula-plugin-example.git"
}
```

---

## Cron & Scheduling

Prefix: `/api/cron`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/cron/jobs` | Yes | List all cron jobs |
| POST | `/api/cron/jobs` | Yes | Create a cron job |
| GET | `/api/cron/jobs/{job_id}` | Yes | Get job details |
| PUT | `/api/cron/jobs/{job_id}` | Yes | Update a cron job |
| DELETE | `/api/cron/jobs/{job_id}` | Yes | Delete a cron job |
| POST | `/api/cron/jobs/{job_id}/run` | Yes | Trigger a job immediately |
| GET | `/api/cron/status` | Yes | Get scheduler status |

### POST /api/cron/jobs

**Request:**
```json
{
  "name": "Daily Summary",
  "schedule": "0 9 * * *",
  "task": "Summarize yesterday's conversations and email me the digest",
  "enabled": true
}
```

```bash
curl -X POST http://localhost:8001/api/cron/jobs \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Hourly Check", "schedule": "0 * * * *", "task": "Check system health"}'
```

---

## Security

Prefix: `/api/security`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/security/audit` | Yes | Run a security audit |
| GET | `/api/security/report` | Yes | Get the latest audit report |
| POST | `/api/security/fix` | Yes | Auto-remediate findings |

### POST /api/security/audit

Runs a security scan of the Ungula configuration and returns findings.

**Response (200):**
```json
{
  "findings": [
    {
      "severity": "high",
      "category": "auth",
      "message": "Default JWT secret key in use",
      "remediation": "Set UNGULA_AUTH_SECRET_KEY environment variable"
    }
  ],
  "score": 65
}
```

---

## Usage & Monitoring

Prefix: `/api/usage`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/usage/summary` | Yes | Token usage summary (all-time totals) |
| GET | `/api/usage/daily` | Yes | Token usage for a specific day |
| GET | `/api/usage/history` | Yes | Usage history over a date range |

### GET /api/usage/summary

**Response (200):**
```json
{
  "total_input_tokens": 1250000,
  "total_output_tokens": 430000,
  "total_requests": 892,
  "by_provider": {
    "anthropic": { "input_tokens": 1000000, "output_tokens": 350000, "requests": 650 },
    "openai": { "input_tokens": 250000, "output_tokens": 80000, "requests": 242 }
  }
}
```

### GET /api/usage/daily

**Query parameters:** `date` (YYYY-MM-DD, defaults to today)

```bash
curl "http://localhost:8001/api/usage/daily?date=2026-02-07" \
  -H "Authorization: Bearer TOKEN"
```

### GET /api/usage/history

**Query parameters:** `start` (YYYY-MM-DD), `end` (YYYY-MM-DD)

```bash
curl "http://localhost:8001/api/usage/history?start=2026-02-01&end=2026-02-07" \
  -H "Authorization: Bearer TOKEN"
```

---

## WebSocket Protocol

### Chat WebSocket

**Endpoint:** `ws://localhost:8001/ws`

Real-time chat interface. Connect with a WebSocket client, send JSON messages, receive streamed responses.

**Client message:**
```json
{
  "type": "chat",
  "conversation_id": "uuid",
  "content": "Hello!",
  "token": "jwt-token"
}
```

**Server messages:**
```json
{"type": "chunk", "content": "partial text"}
{"type": "tool_call", "name": "web_search", "args": {"query": "..."}}
{"type": "tool_result", "name": "web_search", "result": "..."}
{"type": "done", "message_id": "uuid", "finish_reason": "end_turn"}
{"type": "error", "code": "...", "message": "..."}
```

### Node WebSocket

**Endpoint:** `ws://localhost:8001/ws/node`

Used by companion devices to maintain a persistent connection to the gateway.

**Node connection:**
```json
{
  "type": "auth",
  "token": "pairing-token",
  "node_id": "node-abc123",
  "capabilities": ["shell", "file_read"]
}
```

**Server commands:**
```json
{
  "type": "invoke",
  "request_id": "uuid",
  "command": "shell",
  "args": {"cmd": "uname -a"}
}
```

**Node response:**
```json
{
  "type": "result",
  "request_id": "uuid",
  "result": "Darwin ...",
  "exit_code": 0
}
```

---

## Health & Info

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | API info (name, version, docs URL) |
| GET | `/api/health` | No | Health check |

### GET /api/health

```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```

---

## Error Format

All errors return a JSON response with a `detail` field:

```json
{
  "detail": "Error description"
}
```

Common HTTP status codes:

| Code | Meaning |
|------|---------|
| 400 | Bad request / validation error |
| 401 | Unauthorized (missing or invalid token) |
| 403 | Forbidden (account deactivated) |
| 404 | Resource not found |
| 409 | Conflict (e.g., duplicate email) |
| 429 | Rate limit exceeded |
| 502 | LLM provider error |
| 500 | Internal server error |
