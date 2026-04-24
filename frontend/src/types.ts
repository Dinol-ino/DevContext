export type NavKey = "chat" | "governance" | "incident" | "settings";
export type ToastTone = "success" | "error" | "warning" | "info";
export type AuthMode = "supabase" | "guest" | null;

export interface HealthResponse {
  status: string;
  version?: string;
}

export interface BackendHealth {
  state: "healthy" | "degraded" | "checking";
  label: string;
  version?: string;
  checkedAt?: string;
  error?: string;
}

export interface ApiSource {
  type?: string;
  label: string;
  url?: string;
}

export interface AskRequest {
  question: string;
  repo_id?: string;
}

export interface AskResponse {
  answer: string;
  confidence: number;
  sources: ApiSource[];
  used_model: string;
}

export interface GovernanceRequest {
  pr_url?: string;
  diff_text: string;
}

export interface GovernanceConflict {
  decision_label: string;
  decision_url?: string;
  explanation: string;
}

export interface GovernanceResponse {
  has_conflicts: boolean;
  conflicts: GovernanceConflict[];
  comment_text: string;
  safe_to_merge: boolean;
}

export interface IncidentRequest {
  alert_title: string;
  service_name: string;
  error_snippet: string;
}

export interface IncidentResponse {
  issue: string;
  likely_cause: string;
  fix_steps: string[];
  warnings: string[];
  severity: string;
  runbook_url?: string;
}

export interface AuthEventRequest {
  event_type: "register" | "login";
  email: string;
  user_id?: string;
  provider?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface AuthEventResponse {
  status: string;
  event_id?: string;
  event_type: string;
  email: string;
}

export interface UserProfile {
  id: string;
  email: string;
  fullName?: string;
  avatarUrl?: string | null;
}

export interface AppToast {
  id: string;
  tone: ToastTone;
  title: string;
  description: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  confidence?: number;
  sources?: ApiSource[];
  status?: "ready" | "loading" | "error";
}
