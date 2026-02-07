import { useState, useEffect } from 'react';
import { cron } from '../api';

const SCHEDULE_KINDS = ['at', 'every', 'cron'];
const ACTION_TYPES = ['agent', 'command', 'webhook'];

const SCHEDULE_PLACEHOLDERS = {
  at: 'HH:MM',
  every: '30m / 2h / 1d',
  cron: '*/5 * * * *',
};

const SCHEDULE_BADGE_COLORS = {
  at: 'bg-blue-600/60 text-blue-200',
  every: 'bg-purple-600/60 text-purple-200',
  cron: 'bg-gray-600 text-gray-200',
};

const EMPTY_FORM = {
  name: '',
  schedule_kind: 'every',
  schedule_value: '',
  action_type: 'agent',
  action_config: '{}',
  enabled: true,
};

function StatusDot({ active }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${active ? 'bg-green-400' : 'bg-red-400'}`}
    />
  );
}

function Badge({ children, className }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${className}`}>
      {children}
    </span>
  );
}

function formatTimestamp(ts) {
  if (!ts) return 'Never';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function Cron() {
  const [jobs, setJobs] = useState([]);
  const [schedulerStatus, setSchedulerStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingJob, setEditingJob] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const is503 = (err) =>
    err && (err.status === 503 || (err.response && err.response.status === 503));

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const [jobsRes, statusRes] = await Promise.all([
        cron.listJobs(),
        cron.status(),
      ]);
      setJobs(jobsRes.jobs || []);
      setSchedulerStatus(statusRes);
    } catch (err) {
      if (is503(err)) {
        setError('Cron scheduler not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to load cron data');
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
  }, []);

  function openCreateModal() {
    setEditingJob(null);
    setForm({ ...EMPTY_FORM });
    setModalOpen(true);
  }

  function openEditModal(job) {
    setEditingJob(job);
    setForm({
      name: job.name || '',
      schedule_kind: job.schedule_kind || 'every',
      schedule_value: job.schedule_value || '',
      action_type: job.action_type || 'agent',
      action_config:
        typeof job.action_config === 'string'
          ? job.action_config
          : JSON.stringify(job.action_config || {}, null, 2),
      enabled: job.enabled !== false,
    });
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setEditingJob(null);
  }

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      let actionConfig = form.action_config;
      try {
        actionConfig = JSON.parse(actionConfig);
      } catch {
        // leave as string if not valid JSON
      }

      const payload = {
        name: form.name,
        schedule_kind: form.schedule_kind,
        schedule_value: form.schedule_value,
        action_type: form.action_type,
        action_config: actionConfig,
        enabled: form.enabled,
      };

      if (editingJob) {
        await cron.updateJob(editingJob.id, payload);
      } else {
        await cron.createJob(payload);
      }

      closeModal();
      await fetchData();
    } catch (err) {
      if (is503(err)) {
        setError('Cron scheduler not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to save job');
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(job) {
    if (!window.confirm(`Delete job "${job.name}"?`)) return;
    try {
      await cron.deleteJob(job.id);
      await fetchData();
    } catch (err) {
      if (is503(err)) {
        setError('Cron scheduler not initialized — check backend configuration');
      } else {
        setError(err.message || 'Failed to delete job');
      }
    }
  }

  async function handleRunNow(job) {
    setFeedback(null);
    try {
      const res = await cron.runJob(job.id);
      setFeedback({ id: job.id, type: 'success', message: res.status || 'Job triggered' });
      await fetchData();
    } catch (err) {
      if (is503(err)) {
        setFeedback({ id: job.id, type: 'error', message: 'Cron scheduler not initialized — check backend configuration' });
      } else {
        setFeedback({ id: job.id, type: 'error', message: err.message || 'Run failed' });
      }
    }
    setTimeout(() => setFeedback(null), 3000);
  }

  const schedulerRunning = schedulerStatus && schedulerStatus.running;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">Cron Jobs</h1>
            {schedulerStatus && (
              <span className="flex items-center gap-1.5 text-sm text-gray-300">
                <StatusDot active={schedulerRunning} />
                {schedulerRunning ? 'Running' : 'Stopped'}
              </span>
            )}
          </div>
          <button
            onClick={openCreateModal}
            className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-3 py-1.5"
          >
            New Job
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {error && (
          <div className="p-3 bg-red-900/50 text-red-200 text-sm rounded">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400">
            Loading...
          </div>
        ) : jobs.length === 0 && !error ? (
          <div className="flex items-center justify-center h-40 text-gray-400">
            No cron jobs configured
          </div>
        ) : (
          jobs.map((job) => (
            <div key={job.id} className="bg-gray-800 rounded-lg p-4 space-y-2">
              {/* Top row: name + enabled indicator */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-bold">{job.name}</span>
                  <StatusDot active={job.enabled !== false} />
                </div>
                <Badge className="bg-gray-600 text-gray-200">
                  {job.action_type}
                </Badge>
              </div>

              {/* Schedule */}
              <div className="flex items-center gap-2 text-sm text-gray-300">
                <Badge className={SCHEDULE_BADGE_COLORS[job.schedule_kind] || 'bg-gray-600 text-gray-200'}>
                  {job.schedule_kind}
                </Badge>
                <span>{job.schedule_value}</span>
              </div>

              {/* Timing info */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-400">
                <span>Last run: {formatTimestamp(job.last_run)}</span>
                <span>Next run: {formatTimestamp(job.next_run)}</span>
                <span>Run count: {job.run_count ?? 0}</span>
              </div>

              {/* Last error */}
              {job.last_error && (
                <div className="text-xs text-red-400 truncate">
                  Error: {job.last_error}
                </div>
              )}

              {/* Run feedback */}
              {feedback && feedback.id === job.id && (
                <div
                  className={`text-xs px-2 py-1 rounded ${
                    feedback.type === 'success'
                      ? 'bg-green-900/50 text-green-200'
                      : 'bg-red-900/50 text-red-200'
                  }`}
                >
                  {feedback.message}
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => handleRunNow(job)}
                  className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-2.5 py-1"
                >
                  Run Now
                </button>
                <button
                  onClick={() => openEditModal(job)}
                  className="bg-gray-600 hover:bg-gray-500 rounded text-sm px-2.5 py-1"
                >
                  Edit
                </button>
                <button
                  onClick={() => handleDelete(job)}
                  className="bg-red-600/50 hover:bg-red-500/50 rounded text-sm px-2.5 py-1"
                >
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Create/Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4 space-y-4">
            <h2 className="text-lg font-semibold">
              {editingJob ? 'Edit Job' : 'New Job'}
            </h2>

            {/* Name */}
            <div className="space-y-1">
              <label className="text-sm text-gray-300">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
                placeholder="My cron job"
              />
            </div>

            {/* Schedule Kind */}
            <div className="space-y-1">
              <label className="text-sm text-gray-300">Schedule Kind</label>
              <select
                value={form.schedule_kind}
                onChange={(e) => updateField('schedule_kind', e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
              >
                {SCHEDULE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>

            {/* Schedule Value */}
            <div className="space-y-1">
              <label className="text-sm text-gray-300">Schedule Value</label>
              <input
                type="text"
                value={form.schedule_value}
                onChange={(e) => updateField('schedule_value', e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
                placeholder={SCHEDULE_PLACEHOLDERS[form.schedule_kind]}
              />
            </div>

            {/* Action Type */}
            <div className="space-y-1">
              <label className="text-sm text-gray-300">Action Type</label>
              <select
                value={form.action_type}
                onChange={(e) => updateField('action_type', e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none"
              >
                {ACTION_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            {/* Action Config */}
            <div className="space-y-1">
              <label className="text-sm text-gray-300">Action Config (JSON)</label>
              <textarea
                value={form.action_config}
                onChange={(e) => updateField('action_config', e.target.value)}
                rows={3}
                className="w-full bg-gray-800 border border-gray-600 rounded text-sm px-3 py-2 focus:ring-1 focus:ring-indigo-500 focus:outline-none font-mono"
                placeholder="{}"
              />
            </div>

            {/* Enabled */}
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="cron-enabled"
                checked={form.enabled}
                onChange={(e) => updateField('enabled', e.target.checked)}
                className="rounded border-gray-600 bg-gray-800 text-indigo-500 focus:ring-indigo-500"
              />
              <label htmlFor="cron-enabled" className="text-sm text-gray-300">
                Enabled
              </label>
            </div>

            {/* Modal actions */}
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={closeModal}
                className="bg-gray-600 hover:bg-gray-500 rounded text-sm px-3 py-1.5"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-500 rounded text-sm px-3 py-1.5 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
