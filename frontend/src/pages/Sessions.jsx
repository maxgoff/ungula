import { useState, useEffect } from 'react';
import { sessions } from '../api';

// Channel names and badge styles
const CHANNEL_NAMES = {
  discord: 'Discord',
  imessage: 'iMessage',
  telegram: 'Telegram',
};

const ChannelBadge = ({ channel }) => {
  const styles = {
    discord: 'bg-indigo-500/20 text-indigo-400',
    imessage: 'bg-green-500/20 text-green-400',
    telegram: 'bg-sky-500/20 text-sky-400',
  };

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${styles[channel] || 'bg-gray-500/20 text-gray-400'}`}>
      {CHANNEL_NAMES[channel] || channel}
    </span>
  );
};

function SessionCard({ session, onClick }) {
  return (
    <button
      onClick={() => onClick(session)}
      className="w-full text-left bg-gray-800 rounded-lg p-4 hover:bg-gray-700/80 transition-colors"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${session.active ? 'bg-green-500' : 'bg-gray-500'}`} />
          <span className="font-medium">{session.contact}</span>
        </div>
        <ChannelBadge channel={session.channel} />
      </div>

      <p className="text-sm text-gray-400 truncate mb-2">{session.lastMessage || 'No messages yet'}</p>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{session.lastActivity}</span>
        <span>{session.messageCount} messages</span>
      </div>
    </button>
  );
}

export default function Sessions() {
  const [sessionList, setSessionList] = useState([]);
  const [activeCount, setActiveCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [selectedSession, setSelectedSession] = useState(null);

  // Fetch sessions
  useEffect(() => {
    async function fetchSessions() {
      setLoading(true);
      setError(null);
      try {
        const params = {};
        if (filter === 'active') params.active = true;
        else if (filter === 'discord' || filter === 'imessage' || filter === 'telegram') params.channel = filter;

        const data = await sessions.list(params);
        setSessionList(data.sessions || []);
        setActiveCount(data.active_count || 0);
      } catch (err) {
        console.warn('Failed to fetch sessions:', err);
        setError('Failed to load sessions');
        setSessionList([]);
      } finally {
        setLoading(false);
      }
    }
    fetchSessions();
  }, [filter]);

  // Handle archive session
  const handleArchiveSession = async () => {
    if (!selectedSession) return;

    try {
      await sessions.delete(selectedSession.id);
      setSessionList((prev) => prev.filter((s) => s.id !== selectedSession.id));
      setSelectedSession(null);
    } catch (err) {
      console.error('Failed to archive session:', err);
      alert('Failed to archive session');
    }
  };

  const filteredSessions = sessionList;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <h1 className="text-xl font-semibold">Sessions</h1>
        <p className="text-sm text-gray-400">
          {activeCount} active sessions
        </p>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b border-gray-700 px-2">
        {['all', 'active', 'telegram', 'discord', 'imessage'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors ${
              filter === f
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {CHANNEL_NAMES[f] || f}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="h-full flex items-center justify-center text-gray-500">
            <p>Loading...</p>
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-red-400">
            <p>{error}</p>
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-500">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
              <p>No sessions found</p>
              <p className="text-sm mt-2">
                Sessions will appear here when contacts message you via Telegram, Discord, or iMessage.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-w-6xl">
            {filteredSessions.map((session) => (
              <SessionCard
                key={session.id}
                session={session}
                onClick={setSelectedSession}
              />
            ))}
          </div>
        )}
      </div>

      {/* Session detail modal */}
      {selectedSession && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-medium">Session Details</h2>
              <button
                onClick={() => setSelectedSession(null)}
                className="text-gray-400 hover:text-white"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-sm text-gray-400">Contact</label>
                <p className="font-medium">{selectedSession.contact}</p>
              </div>

              <div>
                <label className="text-sm text-gray-400">Channel</label>
                <p>
                  <ChannelBadge channel={selectedSession.channel} />
                </p>
              </div>

              <div>
                <label className="text-sm text-gray-400">Status</label>
                <p className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${selectedSession.active ? 'bg-green-500' : 'bg-gray-500'}`} />
                  {selectedSession.active ? 'Active' : 'Inactive'}
                </p>
              </div>

              <div>
                <label className="text-sm text-gray-400">Messages</label>
                <p>{selectedSession.messageCount} total</p>
              </div>

              <div>
                <label className="text-sm text-gray-400">Last Activity</label>
                <p>{selectedSession.lastActivity}</p>
              </div>
            </div>

            <div className="mt-6 flex gap-2">
              <button
                onClick={handleArchiveSession}
                className="flex-1 px-4 py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg transition-colors"
              >
                Archive
              </button>
              <button
                onClick={() => setSelectedSession(null)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
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
