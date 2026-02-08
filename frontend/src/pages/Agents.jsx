import { useState, useEffect } from 'react';
import { agents, config } from '../api';

const AGENT_TYPES = ['orchestrator', 'coder', 'researcher', 'writer', 'analyst', 'custom'];

function AgentForm({ agent, onSave, onCancel, providers }) {
  const [form, setForm] = useState(
    agent || {
      id: '',
      name: '',
      type: 'orchestrator',
      enabled: true,
      provider: '',
      model: '',
      temperature: '',
      max_tokens: '',
      max_tool_iterations: '',
      system_prompt: '',
    }
  );
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);

  // Fetch models when provider changes
  useEffect(() => {
    const providerName = form.provider;
    if (!providerName) {
      setModels([]);
      return;
    }
    let cancelled = false;
    setLoadingModels(true);
    config.getProviderModels(providerName)
      .then((data) => {
        if (!cancelled) setModels(data.models || []);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => { cancelled = true; };
  }, [form.provider]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      for (const key of ['provider', 'model', 'system_prompt', 'persona']) {
        if (payload[key] === '') payload[key] = null;
      }
      for (const key of ['temperature', 'max_tokens', 'max_tool_iterations']) {
        if (payload[key] === '' || payload[key] === null) {
          payload[key] = null;
        } else {
          payload[key] = Number(payload[key]);
        }
      }
      await onSave(payload);
    } finally {
      setSaving(false);
    }
  };

  const enabledProviders = (providers || []).filter((p) => p.enabled && p.healthy !== false);

  return (
    <form onSubmit={handleSubmit} className="bg-gray-750 rounded-lg p-4 space-y-3 border border-gray-600">
      <div className="grid grid-cols-2 gap-3">
        {!agent && (
          <div>
            <label className="block text-xs text-gray-400 mb-1">ID</label>
            <input
              type="text"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
              placeholder="my-agent"
              pattern="^[-a-z0-9_]+$"
              required
            />
          </div>
        )}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Type</label>
          <select
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value })}
            className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
          >
            {AGENT_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Provider</label>
          <select
            value={form.provider || ''}
            onChange={(e) => setForm({ ...form, provider: e.target.value, model: '' })}
            className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
          >
            <option value="">(default)</option>
            {enabledProviders.map((p) => (
              <option key={p.name} value={p.name}>{p.display_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Model {loadingModels && <span className="text-gray-500 ml-1">loading...</span>}
          </label>
          {models.length > 0 ? (
            <select
              value={form.model || ''}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
            >
              <option value="">(default)</option>
              {models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={form.model || ''}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
              placeholder={form.provider ? '(select or type)' : '(default)'}
            />
          )}
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Temperature</label>
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={form.temperature ?? ''}
            onChange={(e) => setForm({ ...form, temperature: e.target.value })}
            className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
            placeholder="0.7"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Max Tokens</label>
          <input
            type="number"
            min="1"
            value={form.max_tokens ?? ''}
            onChange={(e) => setForm({ ...form, max_tokens: e.target.value })}
            className="w-full bg-gray-700 text-white text-sm rounded px-3 py-1.5 border border-gray-600 focus:border-indigo-500 outline-none"
            placeholder="(default)"
          />
        </div>
        <div className="flex items-center gap-2 pt-5">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            className="w-4 h-4 rounded bg-gray-700 border-gray-600 text-indigo-500"
          />
          <label className="text-sm text-gray-300">Enabled</label>
        </div>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">System Prompt</label>
        <textarea
          value={form.system_prompt || ''}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          className="w-full bg-gray-700 text-white text-sm rounded px-3 py-2 border border-gray-600 focus:border-indigo-500 outline-none resize-y"
          rows={3}
          placeholder="Override system prompt (optional)"
        />
      </div>
      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-500 disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving...' : agent ? 'Update' : 'Create'}
        </button>
      </div>
    </form>
  );
}

export default function Agents() {
  const [agentList, setAgentList] = useState([]);
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [showCreate, setShowCreate] = useState(false);

  const fetchAgents = async () => {
    try {
      setLoading(true);
      const data = await agents.list();
      setAgentList(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgents();
    config.getProviders().then((data) => {
      setProviders(data.providers || []);
    }).catch(() => {});
  }, []);

  const handleCreate = async (data) => {
    try {
      await agents.create(data);
      setShowCreate(false);
      setError(null);
      fetchAgents();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleUpdate = async (data) => {
    try {
      await agents.update(data.id, data);
      setEditingId(null);
      setError(null);
      fetchAgents();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm(`Delete agent "${id}"?`)) return;
    try {
      await agents.delete(id);
      setError(null);
      fetchAgents();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Agent Configuration</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition-colors"
        >
          + Add Agent
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {showCreate && (
        <div className="mb-4">
          <AgentForm onSave={handleCreate} onCancel={() => setShowCreate(false)} providers={providers} />
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 text-sm">Loading agents...</div>
      ) : agentList.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg mb-2">No agents configured</p>
          <p className="text-sm">Add an agent to get started with per-agent LLM settings.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {agentList.map((agent) => (
            <div key={agent.id}>
              {editingId === agent.id ? (
                <AgentForm
                  agent={agent}
                  onSave={handleUpdate}
                  onCancel={() => setEditingId(null)}
                  providers={providers}
                />
              ) : (
                <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-2 h-2 rounded-full ${agent.enabled ? 'bg-green-400' : 'bg-gray-500'}`} />
                    <div>
                      <div className="text-white font-medium">{agent.name}</div>
                      <div className="text-xs text-gray-400 flex gap-3 mt-0.5">
                        <span>ID: {agent.id}</span>
                        <span>Type: {agent.type}</span>
                        {agent.provider && <span>Provider: {agent.provider}</span>}
                        {agent.model && <span>Model: {agent.model}</span>}
                        {agent.temperature != null && <span>Temp: {agent.temperature}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setEditingId(agent.id)}
                      className="px-3 py-1 text-xs text-gray-400 hover:text-white border border-gray-600 rounded hover:border-gray-500 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(agent.id)}
                      className="px-3 py-1 text-xs text-red-400 hover:text-red-300 border border-red-800 rounded hover:border-red-600 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
