import { useState, useEffect } from 'react';
import { memory } from '../api';

const TABS = ['Search', 'Add', 'Index', 'Status'];

const TYPE_OPTIONS = ['fact', 'conversation', 'document', 'note'];
const LEVEL_OPTIONS = ['global', 'project', 'agent'];

function TypeBadge({ type }) {
  const colors = {
    fact: 'bg-blue-600/60 text-blue-200',
    conversation: 'bg-purple-600/60 text-purple-200',
    document: 'bg-green-600/60 text-green-200',
    note: 'bg-yellow-600/60 text-yellow-200',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[type] || 'bg-gray-600 text-gray-200'}`}>
      {type}
    </span>
  );
}

function LevelBadge({ level }) {
  const colors = {
    global: 'bg-red-600/60 text-red-200',
    project: 'bg-cyan-600/60 text-cyan-200',
    agent: 'bg-orange-600/60 text-orange-200',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[level] || 'bg-gray-600 text-gray-200'}`}>
      {level}
    </span>
  );
}

function SearchTab() {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [levelFilter, setLevelFilter] = useState('all');
  const [limit, setLimit] = useState(10);
  const [hybrid, setHybrid] = useState(false);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const params = { limit, hybrid };
      if (typeFilter !== 'all') params.type = typeFilter;
      if (levelFilter !== 'all') params.level = levelFilter;
      const data = await memory.search(query, params);
      setResults(data.results || []);
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Search failed');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    setError(null);
    try {
      await memory.remove(id);
      setResults((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Delete failed');
      }
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search memories..."
          className="flex-1 bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
        />
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50"
        >
          Search
        </button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-1.5 text-sm text-gray-300">
          Type
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="bg-gray-800 border border-gray-600 rounded text-sm px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          >
            <option value="all">All</option>
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-sm text-gray-300">
          Level
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
            className="bg-gray-800 border border-gray-600 rounded text-sm px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          >
            <option value="all">All</option>
            {LEVEL_OPTIONS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-sm text-gray-300">
          Limit
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            min={1}
            max={100}
            className="w-16 bg-gray-800 border border-gray-600 rounded text-sm px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          />
        </label>

        <label className="flex items-center gap-1.5 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={hybrid}
            onChange={(e) => setHybrid(e.target.checked)}
            className="rounded"
          />
          Hybrid
        </label>
      </div>

      {error && (
        <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
      )}

      {loading && (
        <div className="text-center text-gray-400 py-8">Loading...</div>
      )}

      {!loading && results.length === 0 && query && !error && (
        <div className="text-center text-gray-500 py-8 text-sm">No results found</div>
      )}

      <div className="space-y-2">
        {results.map((result) => (
          <div key={result.id} className="bg-gray-700/50 rounded-lg p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-200 whitespace-pre-wrap break-words">
                  {result.content && result.content.length > 300
                    ? result.content.slice(0, 300) + '...'
                    : result.content}
                </p>
                <div className="flex items-center gap-2 mt-2">
                  {result.type && <TypeBadge type={result.type} />}
                  {result.level && <LevelBadge level={result.level} />}
                  {result.score != null && (
                    <span className="text-xs text-gray-400">
                      score: {Number(result.score).toFixed(3)}
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(result.id)}
                className="bg-red-600/50 hover:bg-red-500/50 rounded text-sm px-3 py-1 shrink-0"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddTab() {
  const [content, setContent] = useState('');
  const [type, setType] = useState('fact');
  const [level, setLevel] = useState('global');
  const [source, setSource] = useState('');
  const [metadata, setMetadata] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const handleAdd = async () => {
    if (!content.trim()) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const params = { type, level };
      if (source.trim()) params.source = source.trim();
      if (metadata.trim()) {
        try {
          params.metadata = JSON.parse(metadata);
        } catch {
          setError('Invalid JSON in metadata field');
          setLoading(false);
          return;
        }
      }
      const data = await memory.add(content, params);
      setSuccess(`Memory added (id: ${data.id})`);
      setContent('');
      setMetadata('');
      setSource('');
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to add memory');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      <div>
        <label className="block text-sm text-gray-300 mb-1">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={4}
          placeholder="Enter memory content..."
          className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none resize-y"
        />
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <label className="block text-sm text-gray-300 mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          >
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <div className="flex-1">
          <label className="block text-sm text-gray-300 mb-1">Level</label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          >
            {LEVEL_OPTIONS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm text-gray-300 mb-1">Source (optional)</label>
        <input
          type="text"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="e.g. user-input, document-import"
          className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
        />
      </div>

      <div>
        <label className="block text-sm text-gray-300 mb-1">Metadata (optional JSON)</label>
        <textarea
          value={metadata}
          onChange={(e) => setMetadata(e.target.value)}
          rows={2}
          placeholder='{"key": "value"}'
          className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none resize-y font-mono"
        />
      </div>

      {error && (
        <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
      )}

      {success && (
        <div className="p-3 bg-green-900/50 text-green-200 text-sm rounded">{success}</div>
      )}

      <button
        onClick={handleAdd}
        disabled={loading || !content.trim()}
        className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50"
      >
        {loading ? 'Adding...' : 'Add Memory'}
      </button>
    </div>
  );
}

function IndexTab() {
  const [content, setContent] = useState('');
  const [source, setSource] = useState('');
  const [chunkSize, setChunkSize] = useState(500);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const handleIndex = async () => {
    if (!content.trim() || !source.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await memory.index(content, source, {
        chunkSize,
        chunkOverlap,
      });
      setResult(data);
      setContent('');
      setSource('');
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Indexing failed');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      <div>
        <label className="block text-sm text-gray-300 mb-1">Document Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={8}
          placeholder="Paste bulk document text to index..."
          className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none resize-y"
        />
      </div>

      <div>
        <label className="block text-sm text-gray-300 mb-1">Source (required)</label>
        <input
          type="text"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="e.g. report-2024.pdf, meeting-notes"
          className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
        />
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <label className="block text-sm text-gray-300 mb-1">Chunk Size</label>
          <input
            type="number"
            value={chunkSize}
            onChange={(e) => setChunkSize(Number(e.target.value))}
            min={50}
            max={5000}
            className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          />
        </div>

        <div className="flex-1">
          <label className="block text-sm text-gray-300 mb-1">Chunk Overlap</label>
          <input
            type="number"
            value={chunkOverlap}
            onChange={(e) => setChunkOverlap(Number(e.target.value))}
            min={0}
            max={1000}
            className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
          />
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
      )}

      {result && (
        <div className="p-3 bg-green-900/50 text-green-200 text-sm rounded">
          Indexed successfully: {result.chunks_stored} chunks stored
        </div>
      )}

      <button
        onClick={handleIndex}
        disabled={loading || !content.trim() || !source.trim()}
        className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50"
      >
        {loading ? 'Indexing...' : 'Index Document'}
      </button>
    </div>
  );
}

function StatusTab() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [syncResult, setSyncResult] = useState(null);

  const fetchStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await memory.status();
      setStatus(data);
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to fetch status');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setSyncResult(null);
    try {
      const data = await memory.sync();
      setSyncResult(data);
      await fetchStatus();
    } catch (err) {
      if (err.status === 503) {
        setError('Memory system not initialized — check backend configuration');
      } else {
        setError(err.message || 'Sync failed');
      }
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  if (loading) {
    return <div className="text-center text-gray-400 py-8">Loading...</div>;
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
      )}

      {status && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {Object.entries(status).map(([key, value]) => (
            <div key={key} className="bg-gray-700/50 rounded-lg p-4">
              <div className="text-xs text-gray-400 mb-1">
                {key.replace(/_/g, ' ')}
              </div>
              <div className="text-lg font-semibold text-gray-100">
                {typeof value === 'object' ? JSON.stringify(value) : String(value)}
              </div>
            </div>
          ))}
        </div>
      )}

      {syncResult && (
        <div className="p-3 bg-green-900/50 text-green-200 text-sm rounded">
          Sync complete: {syncResult.status || JSON.stringify(syncResult)}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleSync}
          disabled={syncing}
          className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50"
        >
          {syncing ? 'Syncing...' : 'Sync from Storage'}
        </button>

        <button
          onClick={fetchStatus}
          disabled={loading}
          className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>
    </div>
  );
}

export default function Memory() {
  const [activeTab, setActiveTab] = useState('Search');

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-700 p-4">
        <h1 className="text-xl font-semibold">Memory</h1>
      </div>

      <div className="flex border-b border-gray-700 px-2">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === 'Search' && <SearchTab />}
        {activeTab === 'Add' && <AddTab />}
        {activeTab === 'Index' && <IndexTab />}
        {activeTab === 'Status' && <StatusTab />}
      </div>
    </div>
  );
}
