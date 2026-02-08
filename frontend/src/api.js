/**
 * Ungula API Client
 *
 * Handles all API communication with the backend.
 */

const API_BASE = '/api';

// --- Auth Token Management ---

const TOKEN_KEY = 'ungula_token';

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function isAuthenticated() {
  return !!getToken();
}


class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

// Base fetch wrapper
async function apiFetch(endpoint, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  // Attach Bearer token if available
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  // Handle 401 -- redirect to login
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent('ungula:auth-required'));
    throw new ApiError('Authentication required', 401);
  }

  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {
      // Response may not be JSON
    }
    let message = `Request failed with status ${response.status}`;
    if (data?.detail) {
      if (typeof data.detail === 'string') {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
      }
    }
    throw new ApiError(message, response.status, data);
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return response.json();
  }
  return null;
}

// Auth API
export const auth = {
  async register(email, password, name = null) {
    const data = await apiFetch('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, name }),
    });
    if (data?.access_token) {
      setToken(data.access_token);
    }
    return data;
  },

  async login(email, password) {
    const data = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (data?.access_token) {
      setToken(data.access_token);
    }
    return data;
  },

  async me() {
    return apiFetch('/auth/me');
  },

  logout() {
    clearToken();
    window.dispatchEvent(new CustomEvent('ungula:auth-required'));
  },

  isAuthenticated,
  getToken,
};

// Conversations API
export const conversations = {
  async list() {
    const data = await apiFetch('/conversations/');
    return data.conversations || [];
  },

  async create(title = null) {
    return apiFetch('/conversations/', {
      method: 'POST',
      body: JSON.stringify({ title }),
    });
  },

  async get(id) {
    return apiFetch(`/conversations/${id}`);
  },

  async delete(id) {
    return apiFetch(`/conversations/${id}`, {
      method: 'DELETE',
    });
  },

  async getMessages(id) {
    return apiFetch(`/conversations/${id}/messages`);
  },
};

// Chat API
export const chat = {
  async send(conversationId, content, options = {}) {
    return apiFetch(`/chat/${conversationId}`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        provider: options.provider,
        model: options.model,
        temperature: options.temperature,
        max_tokens: options.maxTokens,
      }),
    });
  },

  // Stream chat response using SSE
  stream(conversationId, content, options = {}) {
    return {
      async *[Symbol.asyncIterator]() {
        const streamHeaders = { 'Content-Type': 'application/json' };
        const streamToken = getToken();
        if (streamToken) {
          streamHeaders['Authorization'] = `Bearer ${streamToken}`;
        }
        const response = await fetch(`${API_BASE}/chat/${conversationId}/stream`, {
          method: 'POST',
          headers: streamHeaders,
          body: JSON.stringify({
            content,
            provider: options.provider,
            model: options.model,
            temperature: options.temperature,
            max_tokens: options.maxTokens,
          }),
        });

        if (!response.ok) {
          throw new ApiError(
            `Stream request failed with status ${response.status}`,
            response.status
          );
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let currentEventType = null;
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7);
              continue;
            }
            if (line.startsWith('data: ')) {
              const data = JSON.parse(line.slice(6));
              if (currentEventType) {
                data._event = currentEventType;
              }
              currentEventType = null;
              yield data;
            }
          }
        }

        // Process any remaining buffer
        if (buffer.startsWith('data: ')) {
          const data = JSON.parse(buffer.slice(6));
          yield data;
        }
      },
    };
  },
};

// Config API
export const config = {
  async get() {
    return apiFetch('/config/');
  },

  async reload() {
    return apiFetch('/config/reload', { method: 'POST' });
  },

  async listWorkspaceFiles() {
    return apiFetch('/config/workspace');
  },

  async getWorkspaceFile(filename) {
    return apiFetch(`/config/workspace/${filename}`);
  },

  async updateWorkspaceFile(filename, content) {
    return apiFetch(`/config/workspace/${filename}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    });
  },

  async getProviders() {
    return apiFetch('/config/providers');
  },

  async updateProvider(name, data) {
    return apiFetch(`/config/providers/${name}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async addCustomProvider(data) {
    return apiFetch('/config/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async deleteProvider(name) {
    return apiFetch(`/config/providers/${name}`, {
      method: 'DELETE',
    });
  },

  async getProviderModels(name) {
    return apiFetch(`/config/providers/${name}/models`);
  },
};

// Channels API
export const channels = {
  async list() {
    return apiFetch('/channels');
  },

  async getHealth(channel) {
    return apiFetch(`/channels/${channel}/health`);
  },

  async start(channel) {
    return apiFetch(`/channels/${channel}/start`, { method: 'POST' });
  },

  async stop(channel) {
    return apiFetch(`/channels/${channel}/stop`, { method: 'POST' });
  },
};

// Inbox API
export const inbox = {
  async list(params = {}) {
    const query = new URLSearchParams();
    if (params.channel) query.set('channel', params.channel);
    if (params.unread !== undefined) query.set('unread', params.unread);
    if (params.limit) query.set('limit', params.limit);
    if (params.offset) query.set('offset', params.offset);
    const queryStr = query.toString();
    return apiFetch(`/channels/inbox${queryStr ? `?${queryStr}` : ''}`);
  },

  async get(messageId) {
    return apiFetch(`/channels/inbox/${messageId}`);
  },

  async markRead(messageId) {
    return apiFetch(`/channels/inbox/${messageId}/read`, { method: 'POST' });
  },

  async markAllRead(sessionId = null) {
    const query = sessionId ? `?session_id=${sessionId}` : '';
    return apiFetch(`/channels/inbox/read${query}`, { method: 'POST' });
  },

  async reply(sessionId, content) {
    return apiFetch('/channels/inbox/reply', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, content }),
    });
  },
};

// Sessions API
export const sessions = {
  async list(params = {}) {
    const query = new URLSearchParams();
    if (params.channel) query.set('channel', params.channel);
    if (params.active !== undefined) query.set('active', params.active);
    if (params.limit) query.set('limit', params.limit);
    if (params.offset) query.set('offset', params.offset);
    const queryStr = query.toString();
    return apiFetch(`/channels/sessions${queryStr ? `?${queryStr}` : ''}`);
  },

  async get(sessionId) {
    return apiFetch(`/channels/sessions/${sessionId}`);
  },

  async delete(sessionId) {
    return apiFetch(`/channels/sessions/${sessionId}`, { method: 'DELETE' });
  },
};

// Skills API
export const skills = {
  async list() {
    return apiFetch('/skills/');
  },

  async get(name) {
    return apiFetch(`/skills/${name}`);
  },

  async enable(name) {
    return apiFetch(`/skills/${name}/enable`, { method: 'POST' });
  },

  async disable(name) {
    return apiFetch(`/skills/${name}/disable`, { method: 'POST' });
  },

  async reload() {
    return apiFetch('/skills/reload', { method: 'POST' });
  },

  async tools() {
    return apiFetch('/skills/tools');
  },

  async uninstall(name) {
    return apiFetch(`/skills/${name}`, { method: 'DELETE' });
  },

  // ClawHub
  async searchClawHub(query) {
    return apiFetch(`/skills/clawhub/search?q=${encodeURIComponent(query)}`);
  },

  async getClawHubSkill(slug) {
    return apiFetch(`/skills/clawhub/${slug}`);
  },

  async checkCompatibility(slug, version = null) {
    return apiFetch('/skills/clawhub/check-compatibility', {
      method: 'POST',
      body: JSON.stringify({ slug, version }),
    });
  },

  async checkSecurity(slug, version = null) {
    return apiFetch('/skills/clawhub/check-security', {
      method: 'POST',
      body: JSON.stringify({ slug, version }),
    });
  },

  async scanInstalled(name) {
    return apiFetch(`/skills/${name}/scan`, {
      method: 'POST',
    });
  },

  async installFromClawHub(slug, version = null, convert = false, force = false, repair = false) {
    return apiFetch('/skills/clawhub/install', {
      method: 'POST',
      body: JSON.stringify({ slug, version, convert, force, repair }),
    });
  },
};

// Memory API
export const memory = {
  async search(query, opts = {}) {
    return apiFetch('/memory/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        memory_type: opts.type,
        level: opts.level,
        limit: opts.limit,
        use_hybrid: opts.hybrid,
      }),
    });
  },

  async add(content, opts = {}) {
    return apiFetch('/memory/add', {
      method: 'POST',
      body: JSON.stringify({
        content,
        memory_type: opts.type,
        level: opts.level,
        source: opts.source,
        metadata: opts.metadata,
      }),
    });
  },

  async remove(id) {
    return apiFetch(`/memory/${id}`, { method: 'DELETE' });
  },

  async sync() {
    return apiFetch('/memory/sync', { method: 'POST' });
  },

  async index(content, source, opts = {}) {
    return apiFetch('/memory/index', {
      method: 'POST',
      body: JSON.stringify({
        content,
        source,
        chunk_size: opts.chunkSize,
        chunk_overlap: opts.chunkOverlap,
      }),
    });
  },

  async status() {
    return apiFetch('/memory/status');
  },
};

// Security API
export const security = {
  async audit() {
    return apiFetch('/security/audit', { method: 'POST' });
  },

  async report() {
    return apiFetch('/security/report');
  },

  async fix(checkIds) {
    return apiFetch('/security/fix', {
      method: 'POST',
      body: JSON.stringify({ check_ids: checkIds }),
    });
  },
};

// Cron API
export const cron = {
  async listJobs() {
    return apiFetch('/cron/jobs');
  },

  async createJob(data) {
    return apiFetch('/cron/jobs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getJob(id) {
    return apiFetch(`/cron/jobs/${id}`);
  },

  async updateJob(id, data) {
    return apiFetch(`/cron/jobs/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async deleteJob(id) {
    return apiFetch(`/cron/jobs/${id}`, { method: 'DELETE' });
  },

  async runJob(id) {
    return apiFetch(`/cron/jobs/${id}/run`, { method: 'POST' });
  },

  async status() {
    return apiFetch('/cron/status');
  },
};

// Pairing API
export const pairing = {
  async verify(code) {
    return apiFetch('/pairing/verify', {
      method: 'POST',
      body: JSON.stringify({ code }),
    });
  },

  async listPending() {
    return apiFetch('/pairing/pending');
  },

  async revoke(code) {
    return apiFetch(`/pairing/${code}`, { method: 'DELETE' });
  },
};

// Subagents API
export const subagents = {
  async spawn(task, parentId = null, metadata = null) {
    const body = { task };
    if (parentId) body.parent_conversation_id = parentId;
    if (metadata) body.metadata = metadata;
    return apiFetch('/subagents/spawn', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  async list(params = {}) {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.parentId) query.set('parent_id', params.parentId);
    const queryStr = query.toString();
    return apiFetch(`/subagents/${queryStr ? `?${queryStr}` : ''}`);
  },

  async get(id) {
    return apiFetch(`/subagents/${id}`);
  },

  async cancel(id) {
    return apiFetch(`/subagents/${id}/cancel`, { method: 'POST' });
  },

  async result(id) {
    return apiFetch(`/subagents/${id}/result`);
  },
};

// Nodes API
export const nodes = {
  async list() {
    return apiFetch('/nodes/');
  },

  async get(id) {
    return apiFetch(`/nodes/${id}`);
  },

  async remove(id) {
    return apiFetch(`/nodes/${id}`, { method: 'DELETE' });
  },

  async listPending() {
    return apiFetch('/nodes/pending');
  },

  async approve(nodeId) {
    return apiFetch(`/nodes/${nodeId}/approve`, { method: 'POST' });
  },

  async reject(nodeId) {
    return apiFetch(`/nodes/${nodeId}/reject`, { method: 'POST' });
  },

  async invoke(nodeId, command, args = {}) {
    return apiFetch(`/nodes/${nodeId}/invoke`, {
      method: 'POST',
      body: JSON.stringify({ command, args }),
    });
  },
};

// Webhooks API
export const webhooks = {
  async create(data) {
    return apiFetch('/webhooks/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async list() {
    return apiFetch('/webhooks/');
  },

  async get(id) {
    return apiFetch(`/webhooks/${id}`);
  },

  async update(id, data) {
    return apiFetch(`/webhooks/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async delete(id) {
    return apiFetch(`/webhooks/${id}`, { method: 'DELETE' });
  },

  async getEvents(id, limit = 20) {
    return apiFetch(`/webhooks/${id}/events?limit=${limit}`);
  },

  async test(id, payload = null) {
    return apiFetch(`/webhooks/${id}/test`, {
      method: 'POST',
      body: JSON.stringify({ payload }),
    });
  },
};

// Plugins API
export const plugins = {
  async list() {
    return apiFetch('/plugins/');
  },

  async get(name) {
    return apiFetch(`/plugins/${name}`);
  },

  async enable(name) {
    return apiFetch(`/plugins/${name}/enable`, { method: 'POST' });
  },

  async disable(name) {
    return apiFetch(`/plugins/${name}/disable`, { method: 'POST' });
  },

  async install(path) {
    return apiFetch('/plugins/install', {
      method: 'POST',
      body: JSON.stringify({ path }),
    });
  },

  async uninstall(name) {
    return apiFetch(`/plugins/${name}`, { method: 'DELETE' });
  },

  async reload() {
    return apiFetch('/plugins/reload', { method: 'POST' });
  },
};

// Agents Config API
export const agents = {
  async list() {
    return apiFetch('/agents/');
  },

  async get(id) {
    return apiFetch(`/agents/${id}`);
  },

  async create(data) {
    return apiFetch('/agents/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async update(id, data) {
    return apiFetch(`/agents/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async delete(id) {
    return apiFetch(`/agents/${id}`, { method: 'DELETE' });
  },
};

// Runtime Config API
export const runtime = {
  async get() {
    return apiFetch('/runtime/');
  },

  async update(data) {
    return apiFetch('/runtime/', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async setDefaultProvider(provider) {
    return apiFetch('/runtime/default-provider', {
      method: 'PUT',
      body: JSON.stringify({ provider }),
    });
  },

  async setDefaultModel(model) {
    return apiFetch('/runtime/default-model', {
      method: 'PUT',
      body: JSON.stringify({ model }),
    });
  },
};

// Token Usage API
export const usage = {
  async summary(params = {}) {
    const query = new URLSearchParams();
    if (params.startDate) query.set('start_date', params.startDate);
    if (params.endDate) query.set('end_date', params.endDate);
    if (params.conversationId) query.set('conversation_id', params.conversationId);
    const queryStr = query.toString();
    return apiFetch(`/usage/summary${queryStr ? `?${queryStr}` : ''}`);
  },

  async daily(days = 30) {
    return apiFetch(`/usage/daily?days=${days}`);
  },

  async history(params = {}) {
    const query = new URLSearchParams();
    if (params.limit) query.set('limit', params.limit);
    if (params.offset) query.set('offset', params.offset);
    if (params.provider) query.set('provider', params.provider);
    if (params.model) query.set('model', params.model);
    const queryStr = query.toString();
    return apiFetch(`/usage/history${queryStr ? `?${queryStr}` : ''}`);
  },
};

// Failover Order API (part of config)
export const failover = {
  async update(order) {
    return apiFetch('/config/failover-order', {
      method: 'PUT',
      body: JSON.stringify({ order }),
    });
  },
};

export { ApiError, getToken, setToken, clearToken, isAuthenticated };
