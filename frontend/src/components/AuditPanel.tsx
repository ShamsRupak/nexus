import { useEffect, useState } from 'react';
import { useApi } from '../hooks/useApi';
import type { AuditEntry } from '../types';

const RISK_STYLE: Record<string, { bg: string; color: string }> = {
  low: { bg: 'rgba(34,197,94,0.12)', color: 'var(--success)' },
  medium: { bg: 'rgba(234,179,8,0.12)', color: 'var(--warning)' },
  high: { bg: 'rgba(239,68,68,0.12)', color: 'var(--danger)' },
  critical: { bg: 'rgba(239,68,68,0.2)', color: 'var(--danger)' },
};

export function AuditPanel() {
  const { getAudit, exportAudit } = useApi();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [filterRisk, setFilterRisk] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);

  const load = () => {
    setLoading(true);
    getAudit({ limit: 50 })
      .then(setEntries)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const filtered = filterRisk === 'all'
    ? entries
    : entries.filter((e) => e.risk_level === filterRisk);

  const handleExport = async (fmt: 'json' | 'csv') => {
    try {
      const result = await exportAudit(fmt);
      const blob = new Blob([result.content], { type: fmt === 'csv' ? 'text/csv' : 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `nexus-audit.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silently fail in demo
    }
  };

  return (
    <div className="border-t" style={{ borderColor: 'var(--border)' }}>
      {/* Header */}
      <div
        className="px-4 py-2.5 flex items-center justify-between cursor-pointer"
        style={{ background: 'var(--bg-secondary)' }}
        onClick={() => setCollapsed((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest"
                style={{ color: 'var(--text-muted)' }}>
            Audit Trail
          </span>
          {entries.length > 0 && (
            <span
              className="text-xs px-1.5 py-0.5 rounded-full"
              style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent)' }}
            >
              {entries.length}
            </span>
          )}
        </div>
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
          {collapsed ? '▲' : '▼'}
        </span>
      </div>

      {!collapsed && (
        <>
          {/* Controls */}
          <div className="px-3 py-2 flex gap-2 items-center flex-wrap"
               style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}>
            <select
              className="text-xs rounded px-2 py-1 flex-1 min-w-0"
              style={{
                background: 'var(--bg-tertiary)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border)',
              }}
              value={filterRisk}
              onChange={(e) => setFilterRisk(e.target.value)}
            >
              <option value="all">All risk levels</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <button
              className="text-xs px-2 py-1 rounded transition-opacity hover:opacity-80"
              style={{
                background: 'var(--bg-tertiary)',
                color: 'var(--text-muted)',
                border: '1px solid var(--border)',
              }}
              onClick={(e) => { e.stopPropagation(); load(); }}
            >
              ↻
            </button>
            <button
              className="text-xs px-2 py-1 rounded transition-opacity hover:opacity-80"
              style={{
                background: 'rgba(99,102,241,0.1)',
                color: 'var(--accent)',
                border: '1px solid rgba(99,102,241,0.2)',
              }}
              onClick={(e) => { e.stopPropagation(); handleExport('csv'); }}
            >
              Export
            </button>
          </div>

          {/* Entries */}
          <div className="overflow-y-auto max-h-64">
            {loading && (
              <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>
                Loading…
              </p>
            )}
            {!loading && filtered.length === 0 && (
              <p className="text-xs py-4 text-center" style={{ color: 'var(--text-muted)' }}>
                No audit entries.
              </p>
            )}
            {filtered.map((entry) => {
              const riskStyle = RISK_STYLE[entry.risk_level] ?? RISK_STYLE.low;
              const ts = new Date(entry.timestamp).toLocaleTimeString();
              return (
                <div
                  key={entry.id}
                  className="px-3 py-2 border-b text-xs"
                  style={{ borderColor: 'var(--border)' }}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span style={{ color: 'var(--text-muted)' }}>{ts}</span>
                    <div className="flex gap-1.5 items-center">
                      <span className="px-1.5 py-0.5 rounded" style={riskStyle}>
                        {entry.risk_level}
                      </span>
                      <span className="px-1.5 py-0.5 rounded"
                            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                        {entry.action_type}
                      </span>
                    </div>
                  </div>
                  <p className="truncate" style={{ color: 'var(--text-secondary)' }}>
                    {entry.input_summary}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {entry.connector} · {entry.duration_ms.toFixed(0)}ms
                  </p>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
