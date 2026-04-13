import { useState } from 'react';
import type { Step } from '../types';

interface Props {
  steps: Step[];
  currentPlanId?: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'var(--text-muted)',
  running: 'var(--accent)',
  completed: 'var(--success)',
  failed: 'var(--danger)',
  skipped: 'var(--text-muted)',
};

const STATUS_BG: Record<string, string> = {
  pending: 'rgba(100,116,139,0.15)',
  running: 'rgba(99,102,241,0.15)',
  completed: 'rgba(34,197,94,0.12)',
  failed: 'rgba(239,68,68,0.12)',
  skipped: 'rgba(100,116,139,0.1)',
};

export function ExecutionTimeline({ steps, currentPlanId }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  if (steps.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12"
           style={{ color: 'var(--text-muted)' }}>
        <svg className="w-8 h-8 mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <p className="text-xs">No active plan</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-1">
      {currentPlanId && (
        <p className="text-xs mb-3 font-mono truncate" style={{ color: 'var(--text-muted)' }}>
          Plan: {currentPlanId.slice(0, 12)}…
        </p>
      )}
      {steps.map((step, idx) => {
        const isExpanded = expanded.has(step.id);
        const color = STATUS_COLORS[step.status] ?? 'var(--text-muted)';
        const bg = STATUS_BG[step.status] ?? 'transparent';
        const isRunning = step.status === 'running';

        return (
          <div key={step.id} className="relative flex gap-3">
            {/* Vertical line */}
            {idx < steps.length - 1 && (
              <div
                className="absolute left-[11px] top-6 bottom-0 w-px"
                style={{ background: 'var(--border)' }}
              />
            )}

            {/* Status dot */}
            <div className="flex-shrink-0 mt-1">
              <div
                className="w-[14px] h-[14px] rounded-full border-2 transition-colors"
                style={{
                  borderColor: color,
                  background: isRunning ? color : 'transparent',
                  animation: isRunning ? 'pulse-dot 1.5s infinite' : 'none',
                }}
              />
            </div>

            {/* Content */}
            <div
              className="flex-1 rounded-lg p-2.5 mb-1 cursor-pointer transition-colors"
              style={{ background: bg, border: `1px solid ${color}22` }}
              onClick={() => toggle(step.id)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                    {step.tool}
                  </p>
                  <p className="text-xs mt-0.5 line-clamp-2 leading-relaxed"
                     style={{ color: 'var(--text-secondary)' }}>
                    {step.description}
                  </p>
                </div>
                <div className="flex-shrink-0 text-right">
                  <span
                    className="text-xs px-1.5 py-0.5 rounded font-medium"
                    style={{ background: bg, color }}
                  >
                    {step.status}
                  </span>
                  {step.duration_ms != null && (
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      {step.duration_ms.toFixed(0)}ms
                    </p>
                  )}
                </div>
              </div>

              {/* Expanded details */}
              {isExpanded && (
                <div className="mt-2 pt-2 border-t space-y-1" style={{ borderColor: 'var(--border)' }}>
                  {step.input && (
                    <div>
                      <span className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
                        Input
                      </span>
                      <pre className="mono text-xs mt-1 p-2 rounded overflow-x-auto"
                           style={{ background: 'var(--bg-primary)', color: 'var(--text-secondary)' }}>
                        {JSON.stringify(step.input, null, 2)}
                      </pre>
                    </div>
                  )}
                  {step.output != null && (
                    <div>
                      <span className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
                        Output
                      </span>
                      <pre className="mono text-xs mt-1 p-2 rounded overflow-x-auto"
                           style={{ background: 'var(--bg-primary)', color: 'var(--text-secondary)' }}>
                        {typeof step.output === 'string' ? step.output : JSON.stringify(step.output, null, 2)}
                      </pre>
                    </div>
                  )}
                  {step.error && (
                    <p className="text-xs p-2 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--danger)' }}>
                      {step.error}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
