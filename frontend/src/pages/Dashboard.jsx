import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { config as configApi, conversations } from '../api';

function formatRelativeTime(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

// Status card component
function StatusCard({ title, value, subtitle, status, icon }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-400">{title}</p>
          <p className="text-2xl font-bold mt-1">{value}</p>
          {subtitle && <p className="text-sm text-gray-500 mt-1">{subtitle}</p>}
        </div>
        <div
          className={`p-2 rounded-lg ${
            status === 'success'
              ? 'bg-green-500/20 text-green-400'
              : status === 'warning'
              ? 'bg-amber-500/20 text-amber-400'
              : status === 'error'
              ? 'bg-red-500/20 text-red-400'
              : 'bg-gray-700 text-gray-400'
          }`}
        >
          {icon}
        </div>
      </div>
    </div>
  );
}

// Activity item component
function ActivityItem({ type, message, timestamp }) {
  const typeStyles = {
    chat: 'bg-indigo-500/20 text-indigo-400',
    error: 'bg-red-500/20 text-red-400',
    system: 'bg-gray-500/20 text-gray-400',
  };

  return (
    <div className="flex items-start gap-3 py-2">
      <div className={`px-2 py-0.5 rounded text-xs ${typeStyles[type] || typeStyles.system}`}>
        {type}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate">{message}</p>
        <p className="text-xs text-gray-500">{timestamp}</p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [systemStatus, setSystemStatus] = useState({
    backend: 'checking',
    ollama: 'checking',
    database: 'checking',
  });
  const [stats, setStats] = useState({
    conversations: 0,
    messages: 0,
    providers: 0,
  });
  const [recentActivity, setRecentActivity] = useState([]);
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    checkHealth();
    loadStats();
  }, []);

  const checkHealth = async () => {
    // Check backend
    try {
      const res = await fetch('/api/health');
      setSystemStatus((prev) => ({
        ...prev,
        backend: res.ok ? 'healthy' : 'unhealthy',
      }));
    } catch {
      setSystemStatus((prev) => ({ ...prev, backend: 'unhealthy' }));
    }

    // Check Ollama
    try {
      const providers = await configApi.getProviders();
      const ollama = providers.providers?.find((p) => p.name === 'ollama');
      setSystemStatus((prev) => ({
        ...prev,
        ollama: ollama?.healthy ? 'healthy' : 'unhealthy',
        database: 'healthy',
      }));
    } catch {
      setSystemStatus((prev) => ({ ...prev, ollama: 'unhealthy', database: 'healthy' }));
    }
  };

  const loadStats = async () => {
    try {
      const [convos, providers] = await Promise.all([
        conversations.list(),
        configApi.getProviders(),
      ]);
      const totalMessages = convos.reduce((sum, c) => sum + (c.message_count || 0), 0);
      const enabledProviders = providers.providers?.filter((p) => p.enabled && p.has_api_key).length || 0;
      setStats({
        conversations: convos.length,
        messages: totalMessages,
        providers: enabledProviders,
      });

      // Build recent activity from real conversations
      const activity = convos
        .filter((c) => c.updated_at)
        .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
        .slice(0, 5)
        .map((c) => ({
          type: 'chat',
          message: c.title || `Conversation ${c.id.slice(0, 8)}`,
          timestamp: formatRelativeTime(c.updated_at),
        }));
      setRecentActivity(activity);
    } catch {
      // Fallback to zeros
    }
  };

  const handleReloadConfig = async () => {
    setReloading(true);
    try {
      await configApi.reload();
      await checkHealth();
      await loadStats();
    } catch {
      // ignore
    }
    setReloading(false);
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'healthy':
        return 'success';
      case 'unhealthy':
        return 'error';
      case 'checking':
        return 'warning';
      default:
        return 'default';
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <p className="text-sm text-gray-400">System overview and health status</p>
      </div>

      <div className="p-4 space-y-6 max-w-6xl">
        {/* System Health */}
        <section>
          <h2 className="text-lg font-medium mb-4">System Health</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <StatusCard
              title="Backend API"
              value={systemStatus.backend === 'healthy' ? 'Online' : 'Offline'}
              subtitle="Ungula v0.1.0"
              status={getStatusColor(systemStatus.backend)}
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"
                  />
                </svg>
              }
            />
            <StatusCard
              title="Ollama"
              value={systemStatus.ollama === 'healthy' ? 'Connected' : 'Disconnected'}
              subtitle="Local LLM server"
              status={getStatusColor(systemStatus.ollama)}
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
              }
            />
            <StatusCard
              title="Database"
              value={systemStatus.database === 'healthy' ? 'Connected' : 'Error'}
              subtitle="SQLite"
              status={getStatusColor(systemStatus.database)}
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                  />
                </svg>
              }
            />
          </div>
        </section>

        {/* Statistics */}
        <section>
          <h2 className="text-lg font-medium mb-4">Statistics</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <StatusCard
              title="Conversations"
              value={stats.conversations}
              subtitle="Total active"
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
              }
            />
            <StatusCard
              title="Messages"
              value={stats.messages}
              subtitle="This session"
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"
                  />
                </svg>
              }
            />
            <StatusCard
              title="Providers"
              value={stats.providers}
              subtitle="Configured"
              icon={
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                  />
                </svg>
              }
            />
          </div>
        </section>

        {/* Recent Activity */}
        <section>
          <h2 className="text-lg font-medium mb-4">Recent Activity</h2>
          <div className="bg-gray-800 rounded-lg p-4">
            {recentActivity.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-4">No recent activity</p>
            ) : (
              <div className="divide-y divide-gray-700">
                {recentActivity.map((activity, idx) => (
                  <ActivityItem key={idx} {...activity} />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Quick Actions */}
        <section>
          <h2 className="text-lg font-medium mb-4">Quick Actions</h2>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={checkHealth}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Refresh Health
            </button>
            <button
              onClick={handleReloadConfig}
              disabled={reloading}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              {reloading ? 'Reloading...' : 'Reload Config'}
            </button>
            <button
              onClick={() => navigate('/config')}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Manage Providers
            </button>
            <button
              onClick={() => navigate('/')}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm transition-colors"
            >
              New Chat
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
