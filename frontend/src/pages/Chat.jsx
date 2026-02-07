import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { conversations, chat } from '../api';

// Message component with markdown support
function Message({ role, content }) {
  const isUser = role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? 'bg-indigo-600 text-white'
            : 'bg-gray-700 text-gray-100'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

// Conversation list sidebar
function ConversationSidebar({
  conversationList,
  currentId,
  onSelect,
  onCreate,
  onDelete,
  loading,
}) {
  return (
    <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
      <div className="p-3 border-b border-gray-700">
        <button
          onClick={onCreate}
          disabled={loading}
          className="w-full py-2 px-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 rounded-md text-sm font-medium transition-colors flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {conversationList.length === 0 ? (
          <p className="p-4 text-sm text-gray-500 text-center">No conversations yet</p>
        ) : (
          <ul className="p-2 space-y-1">
            {conversationList.map((conv) => (
              <li key={conv.id}>
                <button
                  onClick={() => onSelect(conv.id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors group flex items-center justify-between ${
                    currentId === conv.id
                      ? 'bg-gray-700 text-white'
                      : 'text-gray-300 hover:bg-gray-700/50'
                  }`}
                >
                  <span className="truncate flex-1">
                    {conv.title || 'New conversation'}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(conv.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-all"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                      />
                    </svg>
                  </button>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// Main Chat page
export default function Chat() {
  const [conversationList, setConversationList] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState([]);
  const messagesEndRef = useRef(null);

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Load messages when conversation changes
  useEffect(() => {
    if (currentConversationId) {
      loadMessages(currentConversationId);
    } else {
      setMessages([]);
    }
  }, [currentConversationId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const loadConversations = async () => {
    try {
      const data = await conversations.list();
      setConversationList(data);
      // Select first conversation if available and none selected
      if (data.length > 0 && !currentConversationId) {
        setCurrentConversationId(data[0].id);
      }
    } catch (err) {
      console.error('Failed to load conversations:', err);
    }
  };

  const loadMessages = async (id) => {
    try {
      const data = await conversations.get(id);
      setMessages(data.messages || []);
    } catch (err) {
      console.error('Failed to load messages:', err);
    }
  };

  const createConversation = async () => {
    setLoading(true);
    try {
      const conv = await conversations.create();
      setConversationList((prev) => [conv, ...prev]);
      setCurrentConversationId(conv.id);
      setMessages([]);
    } catch (err) {
      console.error('Failed to create conversation:', err);
    } finally {
      setLoading(false);
    }
  };

  const deleteConversation = async (id) => {
    try {
      await conversations.delete(id);
      setConversationList((prev) => prev.filter((c) => c.id !== id));
      if (currentConversationId === id) {
        const remaining = conversationList.filter((c) => c.id !== id);
        setCurrentConversationId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || streaming) return;

    // Create conversation if none exists
    if (!currentConversationId) {
      const conv = await conversations.create();
      setConversationList((prev) => [conv, ...prev]);
      setCurrentConversationId(conv.id);
      // Small delay to ensure state is updated
      await new Promise((resolve) => setTimeout(resolve, 100));
      sendMessage(conv.id, input.trim());
    } else {
      sendMessage(currentConversationId, input.trim());
    }
  };

  const sendMessage = async (conversationId, content) => {
    const userMessage = { role: 'user', content };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setStreaming(true);
    setStreamingContent('');
    setActiveTools([]);

    try {
      const stream = chat.stream(conversationId, content);
      let fullContent = '';

      for await (const event of stream) {
        // Handle tool calling SSE events
        if (event._event === 'tool_call') {
          setActiveTools((prev) => [...prev, { id: event.tool_call_id, name: event.name, status: 'running' }]);
          continue;
        }
        if (event._event === 'tool_result') {
          setActiveTools((prev) =>
            prev.map((t) =>
              t.id === event.tool_call_id
                ? { ...t, status: event.success ? 'done' : 'error', time: event.execution_time_ms }
                : t
            )
          );
          continue;
        }

        if (event.content) {
          fullContent += event.content;
          setStreamingContent(fullContent);
        }
        if (event.finish_reason) {
          // Stream complete
          setMessages((prev) => [...prev, { role: 'assistant', content: fullContent }]);
          setStreamingContent('');
          setActiveTools([]);
        }
        if (event.code) {
          // Error event
          console.error('Stream error:', event.message);
          if (fullContent) {
            setMessages((prev) => [...prev, { role: 'assistant', content: fullContent }]);
          }
          setStreamingContent('');
          setActiveTools([]);
        }
      }
    } catch (err) {
      console.error('Failed to send message:', err);
    } finally {
      setStreaming(false);
      setActiveTools([]);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="h-full flex">
      {/* Sidebar */}
      <ConversationSidebar
        conversationList={conversationList}
        currentId={currentConversationId}
        onSelect={setCurrentConversationId}
        onCreate={createConversation}
        onDelete={deleteConversation}
        loading={loading}
      />

      {/* Chat area */}
      <div className="flex-1 flex flex-col">
        {/* Chat header */}
        <div className="border-b border-gray-700 px-4 py-2 flex items-center">
          <div className="text-sm text-gray-400">
            {currentConversationId
              ? conversationList.find((c) => c.id === currentConversationId)?.title ||
                'New conversation'
              : 'Select or create a conversation'}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
          {messages.length === 0 && !streamingContent ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-gray-500">
                <p className="text-lg mb-2">Start a conversation</p>
                <p className="text-sm">Type a message below to begin chatting</p>
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, idx) => (
                <Message key={idx} role={msg.role} content={msg.content} />
              ))}
              {activeTools.length > 0 && (
                <div className="flex items-center gap-2 px-4 py-2 text-xs text-gray-400">
                  {activeTools.map((t) => (
                    <span key={t.id} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${
                      t.status === 'running' ? 'border-yellow-600 text-yellow-400' :
                      t.status === 'done' ? 'border-green-700 text-green-400' :
                      'border-red-700 text-red-400'
                    }`}>
                      {t.status === 'running' && <span className="animate-spin">&#9881;</span>}
                      {t.name}
                      {t.time != null && <span className="text-gray-500">{t.time}ms</span>}
                    </span>
                  ))}
                </div>
              )}
              {streamingContent && (
                <Message role="assistant" content={streamingContent} />
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-700 p-4">
          <div className="max-w-4xl mx-auto flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              rows={1}
              className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
              disabled={streaming}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || streaming}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              {streaming ? (
                <svg
                  className="w-5 h-5 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              ) : (
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
