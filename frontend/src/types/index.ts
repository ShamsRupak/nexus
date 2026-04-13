export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export type WsEventType =
  | 'classifying'
  | 'intent_classified'
  | 'planning'
  | 'plan_created'
  | 'step_started'
  | 'step_completed'
  | 'step_failed'
  | 'plan_completed'
  | 'approval_required'
  | 'response_chunk'
  | 'error';

export interface WsEvent {
  event: WsEventType;
  trace_id?: string;
  plan_id?: string;
  step_id?: string;
  tool?: string;
  intent?: string;
  requires_approval?: boolean;
  answer?: string;
  error?: string;
  duration_ms?: number;
  step_count?: number;
  steps?: Step[];
  [key: string]: unknown;
}

export interface Step {
  id: string;
  tool: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  duration_ms?: number;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  depends_on?: string[];
}

export interface Plan {
  plan_id: string;
  prompt: string;
  intent: string;
  status: string;
  requires_approval: boolean;
  trace_id: string;
  created_at: string;
  step_count: number;
  latency_ms?: number;
  steps?: Step[];
}

export type MessageRole = 'user' | 'agent' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  plan_id?: string;
  requires_approval?: boolean;
  steps?: Step[];
  isStreaming?: boolean;
  structuredData?: unknown;
}

export interface Connector {
  name: string;
  description: string;
  capabilities: string[];
  healthy?: boolean;
}

export interface AuditEntry {
  id: string;
  trace_id: string;
  timestamp: string;
  action_type: string;
  connector: string;
  input_summary: string;
  output_summary: string;
  approval_status: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  duration_ms: number;
  user_id?: string;
}

export interface HealthStatus {
  status: string;
  version: string;
  components: Record<string, string>;
}
