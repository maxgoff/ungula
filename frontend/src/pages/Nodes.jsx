import { useState, useEffect } from 'react';
import { nodes } from '../api';

const statusColors = {
  online: 'bg-green-500',
  paired: 'bg-blue-500',
  offline: 'bg-gray-500',
  pending: 'bg-yellow-500',
};

const platformIcons = {
  darwin: 'macOS',
  macos: 'macOS',
  linux: 'Linux',
  ios: 'iOS',
  android: 'Android',
  headless: 'Headless',
};

export default function Nodes() {
  const [nodeList, setNodeList] = useState([]);
  const [pendingList, setPendingList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [invokeNodeId, setInvokeNodeId] = useState(null);
  const [invokeCommand, setInvokeCommand] = useState('');
  const [invokeArgs, setInvokeArgs] = useState('');
  const [invokeResult, setInvokeResult] = useState(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [nodesRes, pendingRes] = await Promise.all([
        nodes.list(),
        nodes.listPending(),
      ]);
      setNodeList(nodesRes.nodes || []);
      setPendingList(pendingRes.pending || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleApprove = async (nodeId) => {
    try {
      await nodes.approve(nodeId);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleReject = async (nodeId) => {
    try {
      await nodes.reject(nodeId);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRemove = async (nodeId) => {
    if (!confirm('Remove this node?')) return;
    try {
      await nodes.remove(nodeId);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleInvoke = async (e) => {
    e.preventDefault();
    try {
      let args = {};
      if (invokeArgs.trim()) {
        args = JSON.parse(invokeArgs);
      }
      const result = await nodes.invoke(invokeNodeId, invokeCommand, args);
      setInvokeResult(result);
    } catch (err) {
      setInvokeResult({ error: err.message });
    }
  };

  if (loading && nodeList.length === 0) {
    return <div className="p-6 text-gray-400">Loading nodes...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-white">Nodes</h1>

      {error && (
        <div className="bg-red-900/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Pending Pairing Requests */}
      {pendingList.length > 0 && (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4">
          <h2 className="text-lg font-semibold text-yellow-300 mb-3">Pending Pairing Requests</h2>
          <div className="space-y-2">
            {pendingList.map((req) => (
              <div key={req.node_id} className="flex items-center justify-between bg-gray-800 rounded-lg p-3">
                <div>
                  <span className="text-white font-medium">{req.name}</span>
                  <span className="text-gray-400 ml-2">{platformIcons[req.platform] || req.platform}</span>
                  <div className="text-xs text-gray-500 mt-1">
                    Capabilities: {(req.capabilities || []).join(', ') || 'none'}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleApprove(req.node_id)}
                    className="px-3 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-sm"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleReject(req.node_id)}
                    className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-sm"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Node List */}
      <div className="space-y-3">
        {nodeList.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            No nodes registered. Connect a companion device to get started.
          </div>
        ) : (
          nodeList.map((node) => (
            <div key={node.id} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-3 h-3 rounded-full ${statusColors[node.status] || 'bg-gray-500'}`} />
                  <div>
                    <span className="text-white font-medium">{node.name}</span>
                    <span className="text-gray-400 ml-2 text-sm">
                      {platformIcons[node.platform] || node.platform}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500 capitalize">{node.status}</span>
                  {node.status === 'online' && (
                    <button
                      onClick={() => {
                        setInvokeNodeId(node.id);
                        setInvokeResult(null);
                      }}
                      className="px-2 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-xs"
                    >
                      Invoke
                    </button>
                  )}
                  <button
                    onClick={() => handleRemove(node.id)}
                    className="px-2 py-1 bg-red-600/50 hover:bg-red-600 text-white rounded text-xs"
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {(node.capabilities || []).map((cap) => (
                  <span key={cap} className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">
                    {cap}
                  </span>
                ))}
              </div>
              {node.last_seen && (
                <div className="text-xs text-gray-500 mt-1">
                  Last seen: {new Date(node.last_seen).toLocaleString()}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Invoke Modal */}
      {invokeNodeId && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h2 className="text-lg font-semibold text-white mb-3">
            Invoke Command on {nodeList.find(n => n.id === invokeNodeId)?.name || invokeNodeId}
          </h2>
          <form onSubmit={handleInvoke} className="space-y-3">
            <input
              type="text"
              placeholder="Command (e.g. notify.send, system.run)"
              value={invokeCommand}
              onChange={(e) => setInvokeCommand(e.target.value)}
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm"
            />
            <input
              type="text"
              placeholder='Args JSON (e.g. {"message": "hello"})'
              value={invokeArgs}
              onChange={(e) => setInvokeArgs(e.target.value)}
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm"
            />
            <div className="flex gap-2">
              <button
                type="submit"
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm"
              >
                Send
              </button>
              <button
                type="button"
                onClick={() => { setInvokeNodeId(null); setInvokeResult(null); }}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm"
              >
                Cancel
              </button>
            </div>
          </form>
          {invokeResult && (
            <pre className="mt-3 bg-gray-900 rounded p-3 text-xs text-gray-300 overflow-x-auto">
              {JSON.stringify(invokeResult, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
