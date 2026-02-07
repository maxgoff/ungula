import { useState, useEffect } from 'react';
import { config as configApi } from '../api';

// Workspace files
const WORKSPACE_FILES = [
  { name: 'SOUL.md', description: 'Agent persona and boundaries' },
  { name: 'USER.md', description: 'User context and preferences' },
  { name: 'IDENTITY.md', description: 'Agent identity details' },
  { name: 'AGENTS.md', description: 'Master workspace guide' },
  { name: 'TOOLS.md', description: 'Local tool notes' },
  { name: 'MEMORY.md', description: 'Long-term memory' },
];

function ProviderCard({ provider, onSave, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    enabled: provider.enabled,
    api_key: '',
    default_model: provider.default_model || '',
    base_url: provider.base_url || '',
  });

  const handleSave = async () => {
    setSaving(true);
    const updates = {};
    if (form.enabled !== provider.enabled) updates.enabled = form.enabled;
    if (form.api_key) updates.api_key = form.api_key;
    if (form.default_model !== (provider.default_model || '')) updates.default_model = form.default_model || null;
    if (form.base_url !== (provider.base_url || '')) updates.base_url = form.base_url || null;

    if (Object.keys(updates).length > 0) {
      await onSave(provider.name, updates);
    }
    setSaving(false);
    setEditing(false);
  };

  return (
    <div className="bg-gray-700/50 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`w-3 h-3 rounded-full ${
              provider.healthy === true
                ? 'bg-green-500'
                : provider.healthy === false
                ? 'bg-red-500'
                : 'bg-gray-500'
            }`}
          />
          <div>
            <div className="font-medium">{provider.display_name}</div>
            <div className="text-sm text-gray-400">
              {provider.description || provider.base_url || ''}
            </div>
          </div>
          {provider.local && (
            <span className="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">Local</span>
          )}
          {provider.type === 'custom' && (
            <span className="text-xs px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded">Custom</span>
          )}
          {!provider.enabled && (
            <span className="text-xs px-2 py-0.5 bg-gray-500/20 text-gray-400 rounded">Disabled</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {provider.has_api_key && (
            <span className="text-xs text-green-400">Key set</span>
          )}
          <button
            onClick={() => setEditing(!editing)}
            className="text-sm px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded transition-colors"
          >
            {editing ? 'Cancel' : 'Edit'}
          </button>
          {provider.type === 'custom' && (
            <button
              onClick={() => onDelete(provider.name)}
              className="text-sm px-3 py-1 bg-red-600/50 hover:bg-red-500/50 rounded transition-colors"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {editing && (
        <div className="mt-4 space-y-3 border-t border-gray-600 pt-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="rounded bg-gray-600 border-gray-500"
            />
            <span className="text-sm">Enabled</span>
          </label>

          <div>
            <label className="block text-sm text-gray-400 mb-1">API Key</label>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              placeholder={provider.has_api_key ? '••••••••  (leave blank to keep)' : 'Enter API key'}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Default Model</label>
            <input
              type="text"
              value={form.default_model}
              onChange={(e) => setForm({ ...form, default_model: e.target.value })}
              placeholder="e.g. gpt-4o"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {provider.type === 'builtin' && !provider.local && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">Base URL (optional override)</label>
              <input
                type="text"
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="Leave blank for default"
                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          )}

          <div className="flex justify-end">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded text-sm transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AddProviderForm({ onAdd, onCancel }) {
  const [form, setForm] = useState({
    name: '',
    display_name: '',
    api_key: '',
    base_url: '',
    default_model: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await onAdd({
        name: form.name.toLowerCase().replace(/\s+/g, '-'),
        display_name: form.display_name,
        api_key: form.api_key,
        base_url: form.base_url,
        default_model: form.default_model || null,
      });
    } catch (err) {
      setError(err.message || 'Failed to add provider');
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-gray-700/50 rounded-lg p-4 space-y-3">
      <h3 className="font-medium">Add Custom Provider</h3>
      <p className="text-sm text-gray-400">
        Any OpenAI-compatible API endpoint (e.g., DeepInfra, Together, Fireworks, etc.)
      </p>

      {error && (
        <div className="p-2 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Display Name *</label>
          <input
            type="text"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value, name: e.target.value.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '') })}
            placeholder="e.g. DeepInfra"
            required
            className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">ID</label>
          <input
            type="text"
            value={form.name || form.display_name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '')}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="auto-generated"
            className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 text-gray-400"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm text-gray-400 mb-1">Base URL *</label>
        <input
          type="url"
          value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          placeholder="https://api.deepinfra.com/v1/openai"
          required
          className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div>
        <label className="block text-sm text-gray-400 mb-1">API Key *</label>
        <input
          type="password"
          value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          placeholder="Enter API key"
          required
          className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div>
        <label className="block text-sm text-gray-400 mb-1">Default Model</label>
        <input
          type="text"
          value={form.default_model}
          onChange={(e) => setForm({ ...form, default_model: e.target.value })}
          placeholder="e.g. meta-llama/Llama-3.3-70B-Instruct"
          className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded text-sm transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving || !form.display_name || !form.api_key || !form.base_url}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded text-sm transition-colors disabled:opacity-50"
        >
          {saving ? 'Adding...' : 'Add Provider'}
        </button>
      </div>
    </form>
  );
}

function WorkspaceEditor({ file, onSave }) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadFile();
  }, [file]);

  const loadFile = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await configApi.getWorkspaceFile(file.name);
      setContent(data.content || '');
    } catch (err) {
      setError('Failed to load file');
      setContent('');
    }
    setLoading(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await configApi.updateWorkspaceFile(file.name, content);
      onSave?.();
    } catch (err) {
      setError('Failed to save file');
    }
    setSaving(false);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-3 border-b border-gray-700">
        <div>
          <div className="font-medium">{file.name}</div>
          <div className="text-sm text-gray-400">{file.description}</div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadFile}
            disabled={loading}
            className="text-sm px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
          >
            Reload
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="text-sm px-3 py-1 bg-indigo-600 hover:bg-indigo-500 rounded transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-2 bg-red-900/50 text-red-200 text-sm">{error}</div>
      )}

      <div className="flex-1 relative">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full" />
          </div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="w-full h-full p-4 bg-gray-900 text-gray-100 font-mono text-sm resize-none focus:outline-none"
            spellCheck={false}
          />
        )}
      </div>
    </div>
  );
}

export default function Config() {
  const [providers, setProviders] = useState([]);
  const [defaultProvider, setDefaultProvider] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFile, setSelectedFile] = useState(WORKSPACE_FILES[0]);
  const [activeTab, setActiveTab] = useState('providers');

  useEffect(() => {
    loadProviders();
  }, []);

  const loadProviders = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await configApi.getProviders();
      setProviders(data.providers);
      setDefaultProvider(data.default_provider);
    } catch (err) {
      setError('Failed to load providers');
    }
    setLoading(false);
  };

  const handleUpdateProvider = async (name, updates) => {
    const data = await configApi.updateProvider(name, updates);
    setProviders(data.providers);
    setDefaultProvider(data.default_provider);
  };

  const handleAddProvider = async (providerData) => {
    const data = await configApi.addCustomProvider(providerData);
    setProviders(data.providers);
    setDefaultProvider(data.default_provider);
    setShowAddForm(false);
  };

  const handleDeleteProvider = async (name) => {
    if (!confirm(`Delete custom provider "${name}"?`)) return;
    const data = await configApi.deleteProvider(name);
    setProviders(data.providers);
    setDefaultProvider(data.default_provider);
  };

  const healthyCount = providers.filter((p) => p.healthy === true).length;
  const enabledCount = providers.filter((p) => p.enabled).length;

  const builtinProviders = providers.filter((p) => p.type === 'builtin');
  const customProviders = providers.filter((p) => p.type === 'custom');

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <h1 className="text-xl font-semibold">Configuration</h1>
        <p className="text-sm text-gray-400">
          Manage providers, models, and workspace files
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        <button
          onClick={() => setActiveTab('providers')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'providers'
              ? 'text-indigo-400 border-b-2 border-indigo-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Providers
        </button>
        <button
          onClick={() => setActiveTab('workspace')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'workspace'
              ? 'text-indigo-400 border-b-2 border-indigo-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Workspace Files
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'providers' && (
          <div className="p-4 overflow-y-auto h-full">
            <div className="max-w-2xl">
              {error && (
                <div className="mb-4 p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
              )}

              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full" />
                </div>
              ) : (
                <>
                  {/* Header */}
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h2 className="font-medium">LLM Providers</h2>
                      <p className="text-sm text-gray-400">
                        {healthyCount}/{enabledCount} healthy
                      </p>
                    </div>
                    <button
                      onClick={loadProviders}
                      className="text-sm px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded transition-colors"
                    >
                      Refresh
                    </button>
                  </div>

                  {/* Built-in Providers */}
                  <div className="space-y-2 mb-6">
                    {builtinProviders.map((provider) => (
                      <ProviderCard
                        key={provider.name}
                        provider={provider}
                        onSave={handleUpdateProvider}
                        onDelete={handleDeleteProvider}
                      />
                    ))}
                  </div>

                  {/* Custom Providers */}
                  <div className="border-t border-gray-700 pt-4">
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="font-medium">Custom Providers</h2>
                      {!showAddForm && (
                        <button
                          onClick={() => setShowAddForm(true)}
                          className="text-sm px-3 py-1 bg-indigo-600 hover:bg-indigo-500 rounded transition-colors"
                        >
                          + Add Provider
                        </button>
                      )}
                    </div>

                    {customProviders.length === 0 && !showAddForm && (
                      <p className="text-sm text-gray-500 py-4">
                        No custom providers configured. Add any OpenAI-compatible endpoint.
                      </p>
                    )}

                    <div className="space-y-2">
                      {customProviders.map((provider) => (
                        <ProviderCard
                          key={provider.name}
                          provider={provider}
                          onSave={handleUpdateProvider}
                          onDelete={handleDeleteProvider}
                        />
                      ))}
                    </div>

                    {showAddForm && (
                      <div className="mt-3">
                        <AddProviderForm
                          onAdd={handleAddProvider}
                          onCancel={() => setShowAddForm(false)}
                        />
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {activeTab === 'workspace' && (
          <div className="flex h-full">
            {/* File list */}
            <div className="w-48 border-r border-gray-700 overflow-y-auto">
              {WORKSPACE_FILES.map((file) => (
                <button
                  key={file.name}
                  onClick={() => setSelectedFile(file)}
                  className={`w-full text-left px-4 py-2 text-sm transition-colors ${
                    selectedFile.name === file.name
                      ? 'bg-gray-700 text-white'
                      : 'text-gray-400 hover:bg-gray-700/50 hover:text-white'
                  }`}
                >
                  {file.name}
                </button>
              ))}
            </div>

            {/* Editor */}
            <div className="flex-1">
              <WorkspaceEditor
                file={selectedFile}
                onSave={() => {}}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
