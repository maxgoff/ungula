import { useState, useEffect } from 'react';
import { subagents } from '../api';

const STATUS_BADGES = {
  pending: 'bg-gray-500/20 text-gray-400',
  running: 'bg-blue-500/20 text-blue-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
  cancelled: 'bg-yellow-500/20 text-yellow-400',
};

const TABS = ['all', 'pending', 'running', 'completed', 'failed', 'cancelled'];

function formatTimestamp(ts) {
  if (!ts) return '';
  return new Date(ts).toLocaleString();
}

function truncateId(id) {
  if (!id) return '';
  if (id.length <= 12) return id;
  return id.slice(0, 12) + '...';
}

export default function Subagents() {
  const [sessions, setSessions] = useState([]);
  const [activeTab, setActiveTab] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showSpawnModal, setShowSpawnModal] = useState(false);
  const [spawnTask, setSpawnTask] = useState('');
  const [spawnParentId, setSpawnParentId] = useState('');
  const [spawning, setSpawning] = useState(false);

  const [showResultModal, setShowResultModal] = useState(false);
  const [resultData, setResultData] = useState(null);
  const [resultLoading, setResultLoading] = useState(false);

  const fetchSessions = async (status) => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (status && status !== 'all') {
        params.status = status;
      }
      const data = await subagents.list(params);
      setSessions(data.sessions || []);
    } catch (err) {
      if (err.status === 503) {
        setError('Subagents system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to fetch subagent sessions');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions(activeTab);
  }, [activeTab]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
  };

  const handleSpawn = async () => {
    if (!spawnTask.trim()) return;
    setSpawning(true);
    try {
      await subagents.spawn(spawnTask.trim(), spawnParentId.trim() || undefined);
      setSpawnTask('');
      setSpawnParentId('');
      setShowSpawnModal(false);
      fetchSessions(activeTab);
    } catch (err) {
      if (err.status === 503) {
        setError('Subagents system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to spawn subagent');
      }
    } finally {
      setSpawning(false);
    }
  };

  const handleCancel = async (id) => {
    try {
      await subagents.cancel(id);
      fetchSessions(activeTab);
    } catch (err) {
      if (err.status === 503) {
        setError('Subagents system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to cancel subagent');
      }
    }
  };

  const handleViewResult = async (id) => {
    setShowResultModal(true);
    setResultData(null);
    setResultLoading(true);
    try {
      const data = await subagents.result(id);
      setResultData(data.result);
    } catch (err) {
      if (err.status === 503) {
        setResultData({ error: 'Subagents system not initialized — check backend configuration' });
      } else {
        setResultData({ error: err.message || 'Failed to fetch result' });
      }
    } finally {
      setResultLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-700 p-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Subagents</h1>
        <button
          onClick={() => setShowSpawnModal(true)}
          className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2"
        >
          Spawn
        </button>
      </div>

      <div className="flex border-b border-gray-700 px-2">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => handleTabChange(tab)}
            className={`px-3 py-2 text-sm capitalize ${
              activeTab === tab
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-3">
        {error && (
          <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-32">
            <span className="text-gray-400">Loading...</span>
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-gray-400">
            <p className="text-sm font-medium">No subagent sessions</p>
            <p className="text-xs mt-1">Spawn a subagent to delegate tasks autonomously.</p>
          </div>
        ) : (
          sessions.map((session) => (
            <div key={session.id} className="bg-gray-800 rounded-lg p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm line-clamp-2">{session.task}</p>
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        STATUS_BADGES[session.status] || STATUS_BADGES.pending
                      }`}
                    >
                      {session.status}
                    </span>
                    {session.parent_conversation_id && (
                      <span className="text-xs text-gray-500" title={session.parent_conversation_id}>
                        Parent: {truncateId(session.parent_conversation_id)}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-4 mt-2 text-xs text-gray-500">
                    <span>Created: {formatTimestamp(session.created_at)}</span>
                    <span>Updated: {formatTimestamp(session.updated_at)}</span>
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  {(session.status === 'running' || session.status === 'pending') && (
                    <button
                      onClick={() => handleCancel(session.id)}
                      className="bg-red-600/50 hover:bg-red-500/50 rounded text-sm px-3 py-1"
                    >
                      Cancel
                    </button>
                  )}
                  {session.status === 'completed' && (
                    <button
                      onClick={() => handleViewResult(session.id)}
                      className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-3 py-1"
                    >
                      View Result
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {showSpawnModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
            <h2 className="text-lg font-semibold mb-4">Spawn Subagent</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-300 mb-1">Task</label>
                <textarea
                  rows={4}
                  value={spawnTask}
                  onChange={(e) => setSpawnTask(e.target.value)}
                  placeholder="Describe the task for the subagent..."
                  className="w-full bg-gray-800 border border-gray-600 rounded text-sm focus:ring-1 focus:ring-indigo-500 p-2 resize-none"
                  required
                />
              </div>
              <div>
                <label className="block text-sm text-gray-300 mb-1">Parent Conversation ID</label>
                <input
                  type="text"
                  value={spawnParentId}
                  onChange={(e) => setSpawnParentId(e.target.value)}
                  placeholder="Optional"
                  className="w-full bg-gray-800 border border-gray-600 rounded text-sm focus:ring-1 focus:ring-indigo-500 p-2"
                />
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <button
                  onClick={() => {
                    setShowSpawnModal(false);
                    setSpawnTask('');
                    setSpawnParentId('');
                  }}
                  className="text-sm text-gray-400 hover:text-gray-200 px-3 py-2"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSpawn}
                  disabled={!spawnTask.trim() || spawning}
                  className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {spawning ? 'Spawning...' : 'Spawn'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showResultModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
            <h2 className="text-lg font-semibold mb-4">Subagent Result</h2>
            {resultLoading ? (
              <div className="flex items-center justify-center h-24">
                <span className="text-gray-400">Loading...</span>
              </div>
            ) : (
              <pre className="bg-gray-900 rounded p-4 text-sm overflow-auto max-h-96 whitespace-pre-wrap">
                {JSON.stringify(resultData, null, 2)}
              </pre>
            )}
            <div className="flex justify-end mt-4">
              <button
                onClick={() => {
                  setShowResultModal(false);
                  setResultData(null);
                }}
                className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
