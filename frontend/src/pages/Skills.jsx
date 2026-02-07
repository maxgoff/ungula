import { useState, useEffect } from 'react';
import { skills as skillsApi } from '../api';

function SourceBadge({ source }) {
  const styles = {
    bundled: 'bg-indigo-500/20 text-indigo-400',
    user: 'bg-green-500/20 text-green-400',
    clawhub: 'bg-amber-500/20 text-amber-400',
  };
  const labels = {
    bundled: 'Built-in',
    user: 'User',
    clawhub: 'ClawHub',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${styles[source] || styles.user}`}>
      {labels[source] || source}
    </span>
  );
}

function EligibilityIndicator({ eligible, reason }) {
  if (eligible) {
    return (
      <span className="flex items-center gap-1 text-xs text-green-400">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        Eligible
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-red-400">
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
      </svg>
      {reason || 'Not eligible'}
    </span>
  );
}

function SkillCard({ skill, onToggle, onUninstall, onScan }) {
  const [toggling, setToggling] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);

  const handleToggle = async () => {
    setToggling(true);
    try {
      await onToggle(skill.name, skill.enabled);
    } catch {
      // error handled by parent
    }
    setToggling(false);
  };

  const handleUninstall = async () => {
    if (!confirm(`Uninstall skill "${skill.name}"? This cannot be undone.`)) return;
    setUninstalling(true);
    try {
      await onUninstall(skill.name);
    } catch {
      // error handled by parent
    }
    setUninstalling(false);
  };

  const tools = skill.tools || [];

  return (
    <div className="bg-gray-700/50 rounded-lg p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3 min-w-0">
          {skill.emoji && (
            <span className="text-2xl flex-shrink-0">{skill.emoji}</span>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{skill.name}</span>
              <SourceBadge source={skill.source} />
              {!skill.enabled && (
                <span className="text-xs px-2 py-0.5 bg-gray-500/20 text-gray-400 rounded">
                  Disabled
                </span>
              )}
            </div>
            {skill.description && (
              <p className="text-sm text-gray-400 mt-1">{skill.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-4">
          <EligibilityIndicator
            eligible={skill.eligible !== false}
            reason={skill.eligible_reason}
          />
          <button
            onClick={handleToggle}
            disabled={toggling}
            className={`text-sm px-3 py-1 rounded transition-colors disabled:opacity-50 ${
              skill.enabled
                ? 'bg-gray-600 hover:bg-gray-500 text-gray-200'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white'
            }`}
          >
            {toggling ? '...' : skill.enabled ? 'Disable' : 'Enable'}
          </button>
          {skill.source !== 'bundled' && (
            <>
              <button
                onClick={() => onScan(skill.name)}
                className="text-sm px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded transition-colors"
                title="Security scan"
              >
                Scan
              </button>
              <button
                onClick={handleUninstall}
                disabled={uninstalling}
                className="text-sm px-3 py-1 bg-red-600/50 hover:bg-red-500/50 rounded transition-colors disabled:opacity-50"
              >
                {uninstalling ? '...' : 'Uninstall'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tools provided */}
      {tools.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-600">
          <p className="text-xs text-gray-500 mb-1.5">Tools provided</p>
          <div className="flex flex-wrap gap-1.5">
            {tools.map((tool) => (
              <span
                key={typeof tool === 'string' ? tool : tool.name}
                className="text-xs px-2 py-0.5 bg-gray-800 text-gray-300 rounded"
              >
                {typeof tool === 'string' ? tool : tool.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ClawHubResultCard({ result, onInstall, installingSlug, checking }) {
  const isActive = installingSlug === result.slug;

  return (
    <div className="bg-gray-700/50 rounded-lg p-4">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {result.emoji && <span className="text-lg">{result.emoji}</span>}
            <span className="font-medium">{result.name || result.slug}</span>
            {result.version && (
              <span className="text-xs text-gray-500">v{result.version}</span>
            )}
          </div>
          {result.description && (
            <p className="text-sm text-gray-400 mt-1">{result.description}</p>
          )}
          {result.author && (
            <p className="text-xs text-gray-500 mt-1">by {result.author}</p>
          )}
        </div>
        <button
          onClick={() => onInstall(result.slug)}
          disabled={isActive}
          className="text-sm px-3 py-1 bg-indigo-600 hover:bg-indigo-500 rounded transition-colors disabled:opacity-50 flex-shrink-0 ml-4"
        >
          {isActive && checking ? 'Checking...' : isActive ? 'Installing...' : 'Install'}
        </button>
      </div>
      {result.tools && result.tools.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {result.tools.map((tool) => (
            <span
              key={typeof tool === 'string' ? tool : tool.name}
              className="text-xs px-2 py-0.5 bg-gray-800 text-gray-300 rounded"
            >
              {typeof tool === 'string' ? tool : tool.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }) {
  const styles = {
    critical: 'bg-red-500/20 text-red-400',
    high: 'bg-orange-500/20 text-orange-400',
    medium: 'bg-yellow-500/20 text-yellow-400',
    low: 'bg-blue-500/20 text-blue-400',
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[severity] || styles.medium}`}>
      {severity}
    </span>
  );
}

function CompatibilityModal({ report, slug, onCancel, onInstallAsIs, onInstallConvert, installing, converting }) {
  if (!report) return null;

  const platformNames = { darwin: 'macOS', linux: 'Linux', win32: 'Windows' };
  const currentName = platformNames[report.current_platform] || report.current_platform;
  const primaryName = platformNames[report.primary_platform] || report.primary_platform;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg max-w-lg w-full max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <h3 className="text-lg font-semibold">Platform Compatibility Warning</h3>
          </div>
          <p className="text-sm text-gray-400 mt-1">{report.summary}</p>
        </div>

        {/* Issues list */}
        <div className="flex-1 overflow-y-auto p-4">
          <p className="text-sm text-gray-300 mb-3">
            Skill <span className="font-medium text-white">{slug}</span> appears to target{' '}
            <span className="font-medium text-white">{primaryName}</span>. You are running{' '}
            <span className="font-medium text-white">{currentName}</span>.
          </p>

          <div className="flex gap-3 text-xs mb-3">
            {report.critical_count > 0 && (
              <span className="text-red-400">{report.critical_count} critical</span>
            )}
            {report.high_count > 0 && (
              <span className="text-orange-400">{report.high_count} high</span>
            )}
            {report.medium_count > 0 && (
              <span className="text-yellow-400">{report.medium_count} medium</span>
            )}
            {report.low_count > 0 && (
              <span className="text-blue-400">{report.low_count} low</span>
            )}
          </div>

          <div className="space-y-1.5">
            {report.issues.map((issue, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <SeverityBadge severity={issue.severity} />
                <span className="text-gray-300">{issue.description}</span>
                {issue.file_path && issue.file_path !== 'SKILL.md' && (
                  <span className="text-gray-500 text-xs">({issue.file_path})</span>
                )}
              </div>
            ))}
          </div>

          {report.convertible && (
            <p className="text-sm text-gray-400 mt-4 p-3 bg-gray-700/50 rounded">
              AI conversion is available. This will use your LLM to rewrite the skill
              instructions for {currentName}. The original will be preserved as SKILL.md.original.
            </p>
          )}
        </div>

        {/* Action buttons */}
        <div className="p-4 border-t border-gray-700 flex gap-2 justify-end">
          <button
            onClick={onCancel}
            disabled={installing || converting}
            className="px-4 py-2 text-sm bg-gray-700 hover:bg-gray-600 rounded transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onInstallAsIs}
            disabled={installing || converting}
            className="px-4 py-2 text-sm bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
          >
            {installing ? 'Installing...' : 'Install As-Is'}
          </button>
          {report.convertible && (
            <button
              onClick={onInstallConvert}
              disabled={installing || converting}
              className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 rounded transition-colors disabled:opacity-50"
            >
              {converting ? 'Converting...' : 'Install & Convert'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ThreatCategoryBadge({ category }) {
  const styles = {
    obfuscation: 'bg-purple-500/20 text-purple-400',
    remote_execution: 'bg-red-500/20 text-red-400',
    credential_access: 'bg-red-500/20 text-red-400',
    anti_detection: 'bg-orange-500/20 text-orange-400',
    exfiltration: 'bg-red-500/20 text-red-400',
    privilege_escalation: 'bg-orange-500/20 text-orange-400',
    persistence: 'bg-yellow-500/20 text-yellow-400',
    suspicious_network: 'bg-yellow-500/20 text-yellow-400',
    python_risks: 'bg-orange-500/20 text-orange-400',
    suspicious_links: 'bg-blue-500/20 text-blue-400',
  };
  const labels = {
    obfuscation: 'Obfuscation',
    remote_execution: 'Remote Exec',
    credential_access: 'Cred Access',
    anti_detection: 'Anti-Detection',
    exfiltration: 'Exfiltration',
    privilege_escalation: 'Priv Escalation',
    persistence: 'Persistence',
    suspicious_network: 'Suspicious Net',
    python_risks: 'Python Risk',
    suspicious_links: 'Suspicious Link',
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[category] || 'bg-gray-500/20 text-gray-400'}`}>
      {labels[category] || category}
    </span>
  );
}

function SecurityModal({ report, slug, onCancel, onInstallForce, onRepairInstall, installing, repairing }) {
  if (!report) return null;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg max-w-lg w-full max-h-[80vh] flex flex-col border border-red-500/30">
        {/* Header */}
        <div className="p-4 border-b border-red-500/30 bg-red-900/20">
          <div className="flex items-center gap-2">
            <svg className="w-6 h-6 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <h3 className="text-lg font-semibold text-red-300">Security Threats Detected</h3>
          </div>
          <p className="text-sm text-red-200/80 mt-1">{report.summary}</p>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-gray-400">Risk:</span>
            <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  report.risk_score > 0.7 ? 'bg-red-500' :
                  report.risk_score > 0.4 ? 'bg-orange-500' :
                  report.risk_score > 0.2 ? 'bg-yellow-500' : 'bg-green-500'
                }`}
                style={{ width: `${Math.round(report.risk_score * 100)}%` }}
              />
            </div>
            <span className="text-xs font-mono text-gray-300">
              {Math.round(report.risk_score * 100)}%
            </span>
          </div>
        </div>

        {/* Severity counts */}
        <div className="px-4 py-2 flex gap-3 text-xs border-b border-gray-700">
          {report.critical_count > 0 && (
            <span className="text-red-400 font-bold">{report.critical_count} CRITICAL</span>
          )}
          {report.high_count > 0 && (
            <span className="text-orange-400">{report.high_count} high</span>
          )}
          {report.medium_count > 0 && (
            <span className="text-yellow-400">{report.medium_count} medium</span>
          )}
          {report.low_count > 0 && (
            <span className="text-blue-400">{report.low_count} low</span>
          )}
        </div>

        {/* Threats list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {report.threats.map((threat, i) => (
            <div key={i} className="bg-gray-900/50 rounded p-3 border border-gray-700">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <SeverityBadge severity={threat.severity} />
                <ThreatCategoryBadge category={threat.category} />
                {threat.file_path && (
                  <span className="text-xs text-gray-500 ml-auto">
                    {threat.file_path}{threat.line_number ? `:${threat.line_number}` : ''}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-200">{threat.description}</p>
              {threat.evidence && (
                <pre className="text-xs text-gray-400 mt-1 bg-gray-800 p-2 rounded overflow-x-auto font-mono">
                  {threat.evidence}
                </pre>
              )}
              {threat.recommendation && (
                <p className="text-xs text-gray-500 mt-1 italic">{threat.recommendation}</p>
              )}
            </div>
          ))}
        </div>

        {/* Actions */}
        <div className="p-4 border-t border-gray-700 flex gap-2 justify-end">
          <button
            onClick={onCancel}
            disabled={installing || repairing}
            className="px-4 py-2 text-sm bg-gray-700 hover:bg-gray-600 rounded transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onRepairInstall}
            disabled={installing || repairing}
            className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 rounded transition-colors disabled:opacity-50"
          >
            {repairing ? 'Repairing...' : 'Repair & Install'}
          </button>
          {!report.blocked ? (
            <button
              onClick={() => onInstallForce(false)}
              disabled={installing || repairing}
              className="px-4 py-2 text-sm bg-orange-600 hover:bg-orange-500 rounded transition-colors disabled:opacity-50"
            >
              {installing ? 'Installing...' : 'Install Despite Warnings'}
            </button>
          ) : (
            <button
              onClick={() => onInstallForce(true)}
              disabled={installing || repairing}
              className="px-4 py-2 text-sm bg-red-700 hover:bg-red-600 rounded transition-colors disabled:opacity-50 border border-red-500"
            >
              {installing ? 'Installing...' : 'Force Install (DANGEROUS)'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Skills() {
  const [skillsList, setSkillsList] = useState([]);
  const [totalTools, setTotalTools] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('installed');
  const [reloading, setReloading] = useState(false);

  // ClawHub state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [installingSlug, setInstallingSlug] = useState(null);

  // Compatibility state
  const [compatReport, setCompatReport] = useState(null);
  const [compatSlug, setCompatSlug] = useState(null);
  const [checking, setChecking] = useState(false);
  const [converting, setConverting] = useState(false);
  const [modalInstalling, setModalInstalling] = useState(false);

  // Security state
  const [securityReport, setSecurityReport] = useState(null);
  const [securitySlug, setSecuritySlug] = useState(null);
  const [securityInstalling, setSecurityInstalling] = useState(false);
  const [pendingCompatReport, setPendingCompatReport] = useState(null);
  const [pendingForce, setPendingForce] = useState(false);
  const [repairing, setRepairing] = useState(false);

  useEffect(() => {
    loadSkills();
  }, []);

  const loadSkills = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await skillsApi.list();
      setSkillsList(data.skills || []);
      setTotalTools(data.total_tools || 0);
    } catch (err) {
      setError(err.message || 'Failed to load skills');
    }
    setLoading(false);
  };

  const handleToggle = async (name, currentlyEnabled) => {
    setError(null);
    try {
      if (currentlyEnabled) {
        await skillsApi.disable(name);
      } else {
        await skillsApi.enable(name);
      }
      await loadSkills();
    } catch (err) {
      setError(err.message || 'Failed to toggle skill');
    }
  };

  const handleUninstall = async (name) => {
    setError(null);
    try {
      await skillsApi.uninstall(name);
      await loadSkills();
    } catch (err) {
      setError(err.message || 'Failed to uninstall skill');
    }
  };

  const handleReload = async () => {
    setReloading(true);
    setError(null);
    try {
      await skillsApi.reload();
      await loadSkills();
    } catch (err) {
      setError(err.message || 'Failed to reload skills');
    }
    setReloading(false);
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const data = await skillsApi.searchClawHub(searchQuery.trim());
      setSearchResults(data.results || []);
    } catch (err) {
      setSearchError(err.message || 'Search failed');
      setSearchResults([]);
    }
    setSearching(false);
  };

  const handleInstall = async (slug) => {
    setInstallingSlug(slug);
    setSearchError(null);
    setChecking(true);

    try {
      // Run security and compatibility checks in parallel
      const [secReport, compatReportResult] = await Promise.all([
        skillsApi.checkSecurity(slug).catch(() => null),
        skillsApi.checkCompatibility(slug).catch(() => null),
      ]);
      setChecking(false);

      // Security takes priority
      if (secReport && !secReport.safe) {
        setSecurityReport(secReport);
        setSecuritySlug(slug);
        // Store compat report for later if also incompatible
        if (compatReportResult && !compatReportResult.compatible) {
          setPendingCompatReport(compatReportResult);
        }
        return; // SecurityModal handles next steps
      }

      // No security issues; check compatibility
      if (compatReportResult && !compatReportResult.compatible) {
        setCompatReport(compatReportResult);
        setCompatSlug(slug);
        return; // CompatibilityModal handles next steps
      }

      // Both clean: install directly
      try {
        await skillsApi.installFromClawHub(slug);
        await loadSkills();
      } catch (err) {
        setSearchError(err.message || 'Installation failed');
      }
      setInstallingSlug(null);
    } catch (err) {
      setChecking(false);
      if (confirm('Pre-install checks failed. Install anyway?')) {
        try {
          await skillsApi.installFromClawHub(slug, null, false, true);
          await loadSkills();
        } catch (installErr) {
          setSearchError(installErr.message || 'Installation failed');
        }
      }
      setInstallingSlug(null);
    }
  };

  const handleSecurityCancel = () => {
    setSecurityReport(null);
    setSecuritySlug(null);
    setPendingCompatReport(null);
    setPendingForce(false);
    setInstallingSlug(null);
  };

  const handleSecurityForceInstall = async (force) => {
    // If there's a pending compat report, show that next
    if (pendingCompatReport) {
      setPendingForce(force);
      setCompatReport(pendingCompatReport);
      setCompatSlug(securitySlug);
      setSecurityReport(null);
      setSecuritySlug(null);
      setPendingCompatReport(null);
      return;
    }

    // No compat issues -- install directly
    setSecurityInstalling(true);
    setSearchError(null);
    try {
      const result = await skillsApi.installFromClawHub(securitySlug, null, false, force);
      if (result.post_conversion_warning) {
        setSearchError(`Warning: ${result.post_conversion_warning}`);
      }
      await loadSkills();
    } catch (err) {
      const msg = err.data?.detail?.message || err.message || 'Installation failed';
      setSearchError(msg);
    }
    setSecurityInstalling(false);
    setSecurityReport(null);
    setSecuritySlug(null);
    setInstallingSlug(null);
  };

  const handleRepairInstall = async () => {
    setRepairing(true);
    setSearchError(null);
    const needsConvert = !!pendingCompatReport;
    try {
      const result = await skillsApi.installFromClawHub(
        securitySlug, null, needsConvert, false, true
      );
      if (result.repair_error) {
        setSearchError(`Repair failed: ${result.repair_error}`);
      } else if (result.post_conversion_warning) {
        setSearchError(`Warning: ${result.post_conversion_warning}`);
      }
      await loadSkills();
    } catch (err) {
      const msg = err.data?.detail?.message || err.message || 'Repair & install failed';
      setSearchError(msg);
    }
    setRepairing(false);
    setSecurityReport(null);
    setSecuritySlug(null);
    setPendingCompatReport(null);
    setPendingForce(false);
    setInstallingSlug(null);
  };

  const handleScan = async (name) => {
    setError(null);
    try {
      const report = await skillsApi.scanInstalled(name);
      if (!report.safe) {
        setSecurityReport(report);
        setSecuritySlug(name);
      } else {
        setError(null);
        alert(`Security scan passed: ${report.summary}`);
      }
    } catch (err) {
      setError(err.message || 'Scan failed');
    }
  };

  const handleCompatCancel = () => {
    setCompatReport(null);
    setCompatSlug(null);
    setPendingForce(false);
    setInstallingSlug(null);
  };

  const handleCompatInstallAsIs = async () => {
    setModalInstalling(true);
    setSearchError(null);
    try {
      await skillsApi.installFromClawHub(compatSlug, null, false, pendingForce);
      await loadSkills();
    } catch (err) {
      setSearchError(err.message || 'Installation failed');
    }
    setModalInstalling(false);
    setCompatReport(null);
    setCompatSlug(null);
    setPendingForce(false);
    setInstallingSlug(null);
  };

  const handleCompatInstallConvert = async () => {
    setConverting(true);
    setSearchError(null);
    try {
      const result = await skillsApi.installFromClawHub(compatSlug, null, true, pendingForce);
      if (result.conversion_error) {
        setSearchError(`Installed but conversion failed: ${result.conversion_error}`);
      }
      await loadSkills();
    } catch (err) {
      setSearchError(err.message || 'Installation failed');
    }
    setConverting(false);
    setCompatReport(null);
    setCompatSlug(null);
    setPendingForce(false);
    setInstallingSlug(null);
  };

  const enabledCount = skillsList.filter((s) => s.enabled).length;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Skills</h1>
            <p className="text-sm text-gray-400">
              {skillsList.length} skill{skillsList.length !== 1 ? 's' : ''} installed
              {' \u00B7 '}{enabledCount} enabled
              {' \u00B7 '}{totalTools} tool{totalTools !== 1 ? 's' : ''} available
            </p>
          </div>
          <button
            onClick={handleReload}
            disabled={reloading}
            className="flex items-center gap-2 text-sm px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded transition-colors disabled:opacity-50"
          >
            <svg
              className={`w-4 h-4 ${reloading ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            {reloading ? 'Reloading...' : 'Reload'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        <button
          onClick={() => setActiveTab('installed')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'installed'
              ? 'text-indigo-400 border-b-2 border-indigo-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Installed
        </button>
        <button
          onClick={() => setActiveTab('clawhub')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'clawhub'
              ? 'text-indigo-400 border-b-2 border-indigo-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          ClawHub
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'installed' && (
          <div className="p-4 overflow-y-auto h-full">
            <div className="max-w-3xl">
              {error && (
                <div className="mb-4 p-3 bg-red-900/50 text-red-200 text-sm rounded">{error}</div>
              )}

              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full" />
                </div>
              ) : skillsList.length === 0 ? (
                <div className="text-center py-12">
                  <svg
                    className="w-12 h-12 mx-auto text-gray-600 mb-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5"
                    />
                  </svg>
                  <p className="text-gray-400 text-sm">No skills installed</p>
                  <p className="text-gray-500 text-xs mt-1">
                    Browse ClawHub to discover and install skills
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {skillsList.map((skill) => (
                    <SkillCard
                      key={skill.name}
                      skill={skill}
                      onToggle={handleToggle}
                      onUninstall={handleUninstall}
                      onScan={handleScan}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'clawhub' && (
          <div className="p-4 overflow-y-auto h-full">
            <div className="max-w-3xl">
              {/* Search form */}
              <form onSubmit={handleSearch} className="mb-4">
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <svg
                      className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                      />
                    </svg>
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search ClawHub for skills..."
                      className="w-full pl-10 pr-3 py-2 bg-gray-800 border border-gray-600 rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={searching || !searchQuery.trim()}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded text-sm transition-colors disabled:opacity-50"
                  >
                    {searching ? 'Searching...' : 'Search'}
                  </button>
                </div>
              </form>

              {searchError && (
                <div className="mb-4 p-3 bg-red-900/50 text-red-200 text-sm rounded">
                  {searchError}
                </div>
              )}

              {searching ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full" />
                </div>
              ) : searchResults.length > 0 ? (
                <div className="space-y-2">
                  {searchResults.map((result) => (
                    <ClawHubResultCard
                      key={result.slug}
                      result={result}
                      onInstall={handleInstall}
                      installingSlug={installingSlug}
                      checking={checking}
                    />
                  ))}
                </div>
              ) : searchQuery && !searching ? (
                <div className="text-center py-12">
                  <svg
                    className="w-12 h-12 mx-auto text-gray-600 mb-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                  <p className="text-gray-400 text-sm">No results found</p>
                  <p className="text-gray-500 text-xs mt-1">
                    Try a different search term
                  </p>
                </div>
              ) : (
                <div className="text-center py-12">
                  <svg
                    className="w-12 h-12 mx-auto text-gray-600 mb-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                    />
                  </svg>
                  <p className="text-gray-400 text-sm">Search ClawHub</p>
                  <p className="text-gray-500 text-xs mt-1">
                    Discover community-built skills and tools
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Security Modal -- shown first if both present */}
      <SecurityModal
        report={securityReport}
        slug={securitySlug}
        onCancel={handleSecurityCancel}
        onInstallForce={handleSecurityForceInstall}
        onRepairInstall={handleRepairInstall}
        installing={securityInstalling}
        repairing={repairing}
      />

      {/* Compatibility Modal -- shown only if no security modal */}
      {!securityReport && (
        <CompatibilityModal
          report={compatReport}
          slug={compatSlug}
          onCancel={handleCompatCancel}
          onInstallAsIs={handleCompatInstallAsIs}
          onInstallConvert={handleCompatInstallConvert}
          installing={modalInstalling}
          converting={converting}
        />
      )}
    </div>
  );
}
