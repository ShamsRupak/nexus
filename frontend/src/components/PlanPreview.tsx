import type { Step } from '../types';

interface Props {
  planId: string;
  steps: Step[];
  riskLevel?: string;
  prompt?: string;
  onApprove: (planId: string) => void;
  onReject: (planId: string) => void;
}

const RISK_BADGE: Record<string, { bg: string; color: string; label: string }> = {
  low: { bg: 'rgba(34,197,94,0.12)', color: 'var(--success)', label: 'LOW' },
  medium: { bg: 'rgba(234,179,8,0.12)', color: 'var(--warning)', label: 'MEDIUM' },
  high: { bg: 'rgba(239,68,68,0.12)', color: 'var(--danger)', label: 'HIGH' },
  critical: { bg: 'rgba(239,68,68,0.2)', color: 'var(--danger)', label: 'CRITICAL' },
};

export function PlanPreview({ planId, steps, riskLevel = 'medium', prompt, onApprove, onReject }: Props) {
  const risk = RISK_BADGE[riskLevel] ?? RISK_BADGE.medium;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        maxWidth: 540,
      }}
    >
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between"
        style={{ background: 'rgba(239,68,68,0.06)', borderBottom: '1px solid rgba(239,68,68,0.15)' }}
      >
        <div className="flex items-center gap-2">
          <span style={{ color: 'var(--danger)' }}>⚠</span>
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Approval Required
          </span>
        </div>
        <span
          className="text-xs font-bold px-2 py-0.5 rounded"
          style={{ background: risk.bg, color: risk.color }}
        >
          {risk.label} RISK
        </span>
      </div>

      {/* Prompt */}
      {prompt && (
        <div className="px-4 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Prompt</p>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-primary)' }}>{prompt}</p>
        </div>
      )}

      {/* Steps */}
      <div className="px-4 py-3">
        <p className="text-xs font-semibold mb-2 uppercase tracking-wider"
           style={{ color: 'var(--text-muted)' }}>
          Execution Plan ({steps.length} step{steps.length !== 1 ? 's' : ''})
        </p>
        <div className="space-y-2">
          {steps.map((step, idx) => (
            <div
              key={step.id ?? idx}
              className="rounded-lg p-2.5 flex items-start gap-2"
              style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}
            >
              <span
                className="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold"
                style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent)' }}
              >
                {idx + 1}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                  {(step as { tool?: string }).tool ?? 'step'}
                </p>
                <p className="text-xs mt-0.5 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                  {(step as { description?: string }).description ?? ''}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div
        className="px-4 pb-4 pt-2 flex gap-3"
        style={{ borderTop: '1px solid var(--border)' }}
      >
        <button
          onClick={() => onApprove(planId)}
          className="flex-1 py-2 rounded-lg text-sm font-semibold transition-opacity hover:opacity-90"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          Approve All
        </button>
        <button
          onClick={() => onReject(planId)}
          className="flex-1 py-2 rounded-lg text-sm font-semibold transition-colors"
          style={{
            background: 'rgba(239,68,68,0.1)',
            color: 'var(--danger)',
            border: '1px solid rgba(239,68,68,0.25)',
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
