import { useState, useEffect } from 'react';
import { webhooks } from '../api';

export default function Webhooks() {
  const [webhookList, setWebhookList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newPreset, setNewPreset] = useState('generic');
  const [selectedWebhook, setSelectedWebhook] = useState(null);
  const [events, setEvents] = useState([]);

  const fetchWebhooks = async () => {
    try {
      setLoading(true);
      const res = await webhooks.list();
      setWebhookList(res.webhooks || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWebhooks();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await webhooks.create({ name: newName, preset: newPreset });
      setNewName('');
      setShowCreate(false);
      fetchWebhooks();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this webhook?')) return;
    try {
      await webhooks.delete(id);
      fetchWebhooks();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleToggle = async (id, currentEnabled) => {
    try {
      await webhooks.update(id, { enabled: !currentEnabled });
      fetchWebhooks();
    } catch (err) {
      setError(err.message);
    }
  };

  const viewEvents = async (webhook) => {
    setSelectedWebhook(webhook);
    try {
      const res = await webhooks.getEvents(webhook.id);
      setEvents(res.events || []);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleTest = async (id) => {
    try {
      const result = await webhooks.test(id);
      alert(`Test event sent. Processed:\n${result.processed}`);
      if (selectedWebhook?.id === id) {
        viewEvents(selectedWebhook);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const copyUrl = (url) => {
    navigator.clipboard.writeText(`${window.location.origin}/api${url}`);
  };

  if (loading && webhookList.length === 0) {
    return <div className="p-6 text-gray-400">Loading webhooks...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Webhooks</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm"
        >
          {showCreate ? 'Cancel' : 'Create Webhook'}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Create Form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
          <input
            type="text"
            placeholder="Webhook name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm"
            required
          />
          <select
            value={newPreset}
            onChange={(e) => setNewPreset(e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm"
          >
            <option value="generic">Generic</option>
            <option value="github">GitHub</option>
            <option value="stripe">Stripe</option>
            <option value="slack">Slack</option>
          </select>
          <button type="submit" className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm">
            Create
          </button>
        </form>
      )}

      {/* Webhook List */}
      <div className="space-y-3">
        {webhookList.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            No webhooks configured. Create one to receive external events.
          </div>
        ) : (
          webhookList.map((wh) => (
            <div key={wh.id} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-3 h-3 rounded-full ${wh.enabled ? 'bg-green-500' : 'bg-gray-500'}`} />
                  <div>
                    <span className="text-white font-medium">{wh.name}</span>
                    <span className="ml-2 px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">
                      {wh.preset}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyUrl(wh.receive_url)}
                    className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
                    title="Copy receive URL"
                  >
                    Copy URL
                  </button>
                  <button
                    onClick={() => viewEvents(wh)}
                    className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
                  >
                    Events
                  </button>
                  <button
                    onClick={() => handleTest(wh.id)}
                    className="px-2 py-1 bg-indigo-600/50 hover:bg-indigo-600 text-white rounded text-xs"
                  >
                    Test
                  </button>
                  <button
                    onClick={() => handleToggle(wh.id, wh.enabled)}
                    className="px-2 py-1 bg-yellow-600/50 hover:bg-yellow-600 text-white rounded text-xs"
                  >
                    {wh.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => handleDelete(wh.id)}
                    className="px-2 py-1 bg-red-600/50 hover:bg-red-600 text-white rounded text-xs"
                  >
                    Delete
                  </button>
                </div>
              </div>
              <div className="text-xs text-gray-500 mt-2 font-mono">
                POST {wh.receive_url}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Events Panel */}
      {selectedWebhook && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white">
              Events: {selectedWebhook.name}
            </h2>
            <button
              onClick={() => setSelectedWebhook(null)}
              className="text-gray-400 hover:text-white text-sm"
            >
              Close
            </button>
          </div>
          {events.length === 0 ? (
            <div className="text-gray-500 text-sm">No events yet</div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {events.map((evt) => (
                <div key={evt.id} className="bg-gray-900 rounded p-2 text-xs">
                  <div className="flex justify-between text-gray-400">
                    <span className={evt.status === 'processed' ? 'text-green-400' : 'text-red-400'}>
                      {evt.status}
                    </span>
                    <span>{evt.created_at ? new Date(evt.created_at).toLocaleString() : ''}</span>
                  </div>
                  {evt.processed_content && (
                    <div className="text-gray-300 mt-1 whitespace-pre-wrap">
                      {evt.processed_content.slice(0, 200)}
                    </div>
                  )}
                  {evt.error && <div className="text-red-400 mt-1">{evt.error}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
