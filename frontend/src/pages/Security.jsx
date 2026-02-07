import { useState, useEffect } from 'react';
import { security } from '../api';

function Security() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [auditing, setAuditing] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [fixResult, setFixResult] = useState(null);

  const loadReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await security.report();
      setReport(data.report);
    } catch (err) {
      if (err.status === 404) {
        setReport(null);
      } else if (err.status === 503) {
        setError('Security system not initialized — check backend configuration');
      } else {
        setError('Failed to load security report');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReport();
  }, []);

  const runAudit = async () => {
    setAuditing(true);
    setError(null);
    setFixResult(null);
    try {
      const data = await security.audit();
      setReport(data.report);
    } catch (err) {
      if (err.status === 503) {
        setError('Security system not initialized — check backend configuration');
      } else {
        setError('Failed to run security audit');
      }
    } finally {
      setAuditing(false);
    }
  };

  const fixCheck = async (checkId) => {
    setFixing(true);
    setFixResult(null);
    try {
      const data = await security.fix([checkId]);
      setFixResult(data);
      await loadReport();
    } catch (err) {
      if (err.status === 503) {
        setError('Security system not initialized — check backend configuration');
      } else {
        setError('Failed to apply fix');
      }
    } finally {
      setFixing(false);
    }
  };

  const fixAll = async () => {
    if (!report) return;
    const fixableIds = report.checks
      .filter((c) => c.fixable && (c.status === 'fail' || c.status === 'warn'))
      .map((c) => c.id);
    if (fixableIds.length === 0) return;

    setFixing(true);
    setFixResult(null);
    try {
      const data = await security.fix(fixableIds);
      setFixResult(data);
      await loadReport();
    } catch (err) {
      if (err.status === 503) {
        setError('Security system not initialized — check backend configuration');
      } else {
        setError('Failed to apply fixes');
      }
    } finally {
      setFixing(false);
    }
  };

  const statusBadge = (status) => {
    const styles = {
      pass: 'bg-green-500/20 text-green-400',
      fail: 'bg-red-500/20 text-red-400',
      warn: 'bg-yellow-500/20 text-yellow-400',
    };
    return (
      <span className={`text-xs px-2 py-0.5 rounded ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>
        {status}
      </span>
    );
  };

  const severityBadge = (severity) => {
    const styles = {
      low: 'bg-gray-500/20 text-gray-400',
      medium: 'bg-yellow-500/20 text-yellow-400',
      high: 'bg-orange-500/20 text-orange-400',
      critical: 'bg-red-500/20 text-red-400',
    };
    return (
      <span className={`text-xs px-2 py-0.5 rounded ${styles[severity] || 'bg-gray-500/20 text-gray-400'}`}>
        {severity}
      </span>
    );
  };

  const overallStatusBadge = (status) => {
    const styles = {
      pass: 'bg-green-500/20 text-green-400',
      fail: 'bg-red-500/20 text-red-400',
      warn: 'bg-yellow-500/20 text-yellow-400',
    };
    return (
      <span className={`text-xs px-2 py-0.5 rounded ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>
        {status}
      </span>
    );
  };

  const fixableChecks = report
    ? report.checks.filter((c) => c.fixable && (c.status === 'fail' || c.status === 'warn'))
    : [];

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-700 p-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Security</h1>
        <div className="flex items-center gap-3">
          {auditing && <span className="text-sm text-gray-400">Running audit...</span>}
          <button
            onClick={runAudit}
            disabled={auditing}
            className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Run Audit
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {error && (
          <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
        )}

        {fixResult && (
          <div className="p-3 bg-gray-700/50 text-sm rounded">
            Fixed: {fixResult.fixed.length} | Failed: {fixResult.failed.length}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <span className="text-gray-400">Loading...</span>
          </div>
        ) : !report ? (
          <div className="flex items-center justify-center h-64">
            <span className="text-gray-400">No audit report yet. Run an audit to get started.</span>
          </div>
        ) : (
          <>
            <div className="bg-gray-700/50 rounded-lg p-4 flex items-center justify-between">
              <div className="flex items-center gap-4">
                {overallStatusBadge(report.summary.status)}
                <span className="text-sm text-gray-300">
                  {report.checks.length} checks — {report.summary.pass} passed, {report.summary.fail} failed, {report.summary.warn} warnings
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500">
                  {new Date(report.timestamp).toLocaleString()}
                </span>
                {fixableChecks.length > 0 && (
                  <button
                    onClick={fixAll}
                    disabled={fixing}
                    className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Auto-Fix All ({fixableChecks.length})
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-3">
              {report.checks.map((check) => (
                <div key={check.id} className="bg-gray-700/50 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm">{check.name}</span>
                      {statusBadge(check.status)}
                      {severityBadge(check.severity)}
                    </div>
                    {check.fixable && (check.status === 'fail' || check.status === 'warn') && (
                      <button
                        onClick={() => fixCheck(check.id)}
                        disabled={fixing}
                        className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-2 py-1 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Fix
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-gray-400">{check.description}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default Security;
