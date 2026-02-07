import { useState, useEffect } from 'react';
import { plugins } from '../api';

const typeColors = {
  tool: 'bg-blue-600',
  channel: 'bg-green-600',
  provider: 'bg-purple-600',
  memory: 'bg-orange-600',
};

export default function Plugins() {
  const [pluginList, setPluginList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [installPath, setInstallPath] = useState('');

  const fetchPlugins = async () => {
    try {
      setLoading(true);
      const res = await plugins.list();
      setPluginList(res.plugins || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlugins();
  }, []);

  const handleEnable = async (name) => {
    try {
      await plugins.enable(name);
      fetchPlugins();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDisable = async (name) => {
    try {
      await plugins.disable(name);
      fetchPlugins();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleUninstall = async (name) => {
    if (!confirm(`Uninstall plugin "${name}"?`)) return;
    try {
      await plugins.uninstall(name);
      fetchPlugins();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleInstall = async (e) => {
    e.preventDefault();
    try {
      await plugins.install(installPath);
      setInstallPath('');
      fetchPlugins();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleReload = async () => {
    try {
      await plugins.reload();
      fetchPlugins();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading && pluginList.length === 0) {
    return <div className="p-6 text-gray-400">Loading plugins...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Plugins</h1>
        <button
          onClick={handleReload}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded text-sm"
        >
          Reload All
        </button>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-700 rounded-lg p-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Install Form */}
      <form onSubmit={handleInstall} className="flex gap-2">
        <input
          type="text"
          placeholder="Local plugin path (e.g. /path/to/my-plugin)"
          value={installPath}
          onChange={(e) => setInstallPath(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm"
        >
          Install
        </button>
      </form>

      {/* Plugin List */}
      <div className="space-y-3">
        {pluginList.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            No plugins installed. Install one from a local path above.
          </div>
        ) : (
          pluginList.map((plugin) => (
            <div key={plugin.name} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-3 h-3 rounded-full ${plugin.enabled ? 'bg-green-500' : 'bg-gray-500'}`} />
                  <div>
                    <span className="text-white font-medium">{plugin.name}</span>
                    <span className="ml-2 text-gray-400 text-sm">v{plugin.version}</span>
                    <span className={`ml-2 px-2 py-0.5 rounded text-xs text-white ${typeColors[plugin.type] || 'bg-gray-600'}`}>
                      {plugin.type}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {plugin.enabled ? (
                    <button
                      onClick={() => handleDisable(plugin.name)}
                      className="px-2 py-1 bg-yellow-600/50 hover:bg-yellow-600 text-white rounded text-xs"
                    >
                      Disable
                    </button>
                  ) : (
                    <button
                      onClick={() => handleEnable(plugin.name)}
                      className="px-2 py-1 bg-green-600/50 hover:bg-green-600 text-white rounded text-xs"
                    >
                      Enable
                    </button>
                  )}
                  <button
                    onClick={() => handleUninstall(plugin.name)}
                    className="px-2 py-1 bg-red-600/50 hover:bg-red-600 text-white rounded text-xs"
                  >
                    Uninstall
                  </button>
                </div>
              </div>
              {plugin.description && (
                <div className="text-sm text-gray-400 mt-2">{plugin.description}</div>
              )}
              {plugin.error && (
                <div className="text-xs text-red-400 mt-1">{plugin.error}</div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
