import { useState, useEffect } from 'react';
import { pairing } from '../api';

const channelStyles = {
  discord: 'bg-indigo-500/20 text-indigo-400',
  imessage: 'bg-green-500/20 text-green-400',
  telegram: 'bg-sky-500/20 text-sky-400',
};

function ChannelBadge({ channel }) {
  const style = channelStyles[channel] || 'bg-gray-500/20 text-gray-400';
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${style}`}>
      {channel}
    </span>
  );
}

export default function Pairing() {
  const [code, setCode] = useState('');
  const [verifyResult, setVerifyResult] = useState(null);
  const [verifyError, setVerifyError] = useState(null);
  const [verifying, setVerifying] = useState(false);

  const [pendingCodes, setPendingCodes] = useState([]);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingError, setPendingError] = useState(null);

  const fetchPending = async () => {
    setPendingLoading(true);
    setPendingError(null);
    try {
      const data = await pairing.listPending();
      setPendingCodes(data.codes || []);
    } catch (err) {
      if (err.status === 503) {
        setPendingError('Pairing system not initialized — check backend configuration');
      } else {
        setPendingError(err.message || 'Failed to load pending codes');
      }
    } finally {
      setPendingLoading(false);
    }
  };

  useEffect(() => {
    fetchPending();
  }, []);

  const handleVerify = async () => {
    if (!code.trim()) return;
    setVerifying(true);
    setVerifyResult(null);
    setVerifyError(null);
    try {
      const data = await pairing.verify(code.trim());
      setVerifyResult(data.message || 'Code verified successfully');
      setCode('');
      fetchPending();
    } catch (err) {
      if (err.status === 503) {
        setVerifyError('Pairing system not initialized — check backend configuration');
      } else {
        setVerifyError(err.data?.detail || err.message || 'Verification failed');
      }
    } finally {
      setVerifying(false);
    }
  };

  const handleRevoke = async (revokeCode) => {
    try {
      await pairing.revoke(revokeCode);
      setPendingCodes((prev) => prev.filter((c) => c.code !== revokeCode));
    } catch (err) {
      if (err.status === 503) {
        setPendingError('Pairing system not initialized — check backend configuration');
      } else {
        setPendingError(err.message || 'Failed to revoke code');
      }
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-700 p-4">
        <h1 className="text-xl font-semibold">Pairing</h1>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Verify Section */}
        <div>
          <h2 className="text-lg font-medium mb-3">Verify Code</h2>
          <div className="bg-gray-700/50 rounded-lg p-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleVerify()}
                placeholder="Enter pairing code"
                className="flex-1 bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 font-mono focus:ring-1 focus:ring-indigo-500 focus:outline-none"
              />
              <button
                onClick={handleVerify}
                disabled={verifying || !code.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {verifying ? 'Verifying...' : 'Verify'}
              </button>
            </div>
            {verifyResult && (
              <div className="mt-3 p-3 bg-green-900/50 text-green-200 text-sm rounded">
                {verifyResult}
              </div>
            )}
            {verifyError && (
              <div className="mt-3 p-3 bg-red-900/50 text-red-200 text-sm rounded">
                {verifyError}
              </div>
            )}
          </div>
        </div>

        {/* Pending Codes Section */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-lg font-medium">Pending Codes</h2>
            {!pendingLoading && !pendingError && (
              <span className="text-xs px-2 py-0.5 rounded bg-gray-500/20 text-gray-400">
                {pendingCodes.length}
              </span>
            )}
          </div>

          {pendingLoading && (
            <div className="text-center py-8 text-gray-400">Loading...</div>
          )}

          {pendingError && (
            <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">
              {pendingError}
            </div>
          )}

          {!pendingLoading && !pendingError && pendingCodes.length === 0 && (
            <div className="text-center py-8 text-gray-400">
              No pending pairing codes
            </div>
          )}

          {!pendingLoading && !pendingError && pendingCodes.length > 0 && (
            <div className="space-y-3">
              {pendingCodes.map((item) => (
                <div
                  key={item.code}
                  className="bg-gray-700/50 rounded-lg p-4 flex items-center justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-lg">{item.code}</span>
                      <ChannelBadge channel={item.channel} />
                    </div>
                    <div className="text-sm text-gray-400">
                      {item.contact}
                    </div>
                    <div className="text-xs text-gray-500">
                      Created: {new Date(item.created_at).toLocaleString()}
                      {' | '}
                      Expires: {new Date(item.expires_at).toLocaleString()}
                    </div>
                  </div>
                  <button
                    onClick={() => handleRevoke(item.code)}
                    className="bg-red-600/50 hover:bg-red-500/50 rounded text-sm px-3 py-1.5"
                  >
                    Revoke
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
