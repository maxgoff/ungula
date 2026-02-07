import { useState, useEffect } from 'react';
import { inbox } from '../api';

// Channel display names
const CHANNEL_NAMES = {
  discord: 'Discord',
  imessage: 'iMessage',
  telegram: 'Telegram',
};

// Channel icons
const ChannelIcon = ({ channel }) => {
  if (channel === 'discord') {
    return (
      <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center">
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z" />
        </svg>
      </div>
    );
  }
  if (channel === 'telegram') {
    return (
      <div className="w-8 h-8 rounded-full bg-sky-500 flex items-center justify-center">
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
        </svg>
      </div>
    );
  }
  // Default: iMessage / other
  return (
    <div className="w-8 h-8 rounded-full bg-green-600 flex items-center justify-center">
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    </div>
  );
};

function MessageCard({ message, selected, onClick }) {
  return (
    <button
      onClick={() => onClick(message)}
      className={`w-full text-left p-4 border-b border-gray-700 hover:bg-gray-700/50 transition-colors ${
        selected ? 'bg-gray-700' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <ChannelIcon channel={message.channel} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`font-medium truncate ${message.unread ? 'text-white' : 'text-gray-300'}`}>
              {message.sender}
            </span>
            <span className="text-xs text-gray-500 whitespace-nowrap">{message.timestamp}</span>
          </div>
          <p className={`text-sm truncate ${message.unread ? 'text-gray-200' : 'text-gray-400'}`}>
            {message.content}
          </p>
        </div>
        {message.unread && <div className="w-2 h-2 rounded-full bg-indigo-500 mt-2" />}
      </div>
    </button>
  );
}

export default function Inbox() {
  const [messages, setMessages] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [filter, setFilter] = useState('all');
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);

  // Fetch messages
  useEffect(() => {
    async function fetchMessages() {
      setLoading(true);
      setError(null);
      try {
        const params = {};
        if (filter === 'unread') params.unread = true;
        else if (filter === 'discord' || filter === 'imessage' || filter === 'telegram') params.channel = filter;

        const data = await inbox.list(params);
        setMessages(data.messages || []);
        setUnreadCount(data.unread_count || 0);
      } catch (err) {
        console.warn('Failed to fetch inbox:', err);
        setError('Failed to load messages');
        setMessages([]);
      } finally {
        setLoading(false);
      }
    }
    fetchMessages();
  }, [filter]);

  // Handle mark as read
  const handleSelectMessage = async (message) => {
    setSelectedMessage(message);

    // Mark as read if unread
    if (message.unread) {
      try {
        await inbox.markRead(message.id);
        setMessages((prev) =>
          prev.map((m) => (m.id === message.id ? { ...m, unread: false } : m))
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch (err) {
        console.warn('Failed to mark message as read:', err);
      }
    }
  };

  // Handle reply
  const handleReply = async () => {
    if (!selectedMessage || !replyText.trim() || sending) return;

    setSending(true);
    try {
      const result = await inbox.reply(selectedMessage.session_id, replyText.trim());
      if (result.success) {
        setReplyText('');
        // Refresh messages to show the sent reply
        const data = await inbox.list(filter === 'all' ? {} : { channel: filter });
        setMessages(data.messages || []);
      } else {
        alert('Failed to send reply: ' + (result.error || 'Unknown error'));
      }
    } catch (err) {
      console.error('Failed to send reply:', err);
      alert('Failed to send reply');
    } finally {
      setSending(false);
    }
  };

  const filteredMessages = messages;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Inbox</h1>
            <p className="text-sm text-gray-400">
              {unreadCount} unread messages
            </p>
          </div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b border-gray-700 px-2">
        {['all', 'unread', 'telegram', 'discord', 'imessage'].map((f) => (
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
      <div className="flex-1 flex overflow-hidden">
        {/* Message list */}
        <div className="w-96 border-r border-gray-700 overflow-y-auto">
          {loading ? (
            <div className="p-8 text-center text-gray-500">
              <p>Loading...</p>
            </div>
          ) : error ? (
            <div className="p-8 text-center text-red-400">
              <p>{error}</p>
            </div>
          ) : filteredMessages.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <p>No messages</p>
              <p className="text-sm mt-2">
                Messages from Telegram, Discord, and iMessage will appear here when channels are connected.
              </p>
            </div>
          ) : (
            filteredMessages.map((message) => (
              <MessageCard
                key={message.id}
                message={message}
                selected={selectedMessage?.id === message.id}
                onClick={handleSelectMessage}
              />
            ))
          )}
        </div>

        {/* Message detail */}
        <div className="flex-1 flex flex-col">
          {selectedMessage ? (
            <>
              {/* Message header */}
              <div className="p-4 border-b border-gray-700">
                <div className="flex items-center gap-3">
                  <ChannelIcon channel={selectedMessage.channel} />
                  <div>
                    <div className="font-medium">{selectedMessage.sender}</div>
                    <div className="text-sm text-gray-400">
                      via {CHANNEL_NAMES[selectedMessage.channel] || selectedMessage.channel} • {selectedMessage.timestamp}
                    </div>
                  </div>
                </div>
              </div>

              {/* Message content */}
              <div className="flex-1 p-4 overflow-y-auto">
                <div className="bg-gray-800 rounded-lg p-4">
                  <p>{selectedMessage.content}</p>
                </div>
              </div>

              {/* Reply */}
              <div className="p-4 border-t border-gray-700">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleReply()}
                    placeholder="Type a reply..."
                    disabled={sending}
                    className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
                  />
                  <button
                    onClick={handleReply}
                    disabled={!replyText.trim() || sending}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg transition-colors"
                  >
                    {sending ? 'Sending...' : 'Send'}
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <svg className="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                </svg>
                <p>Select a message to view</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
