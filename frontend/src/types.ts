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
  thread_id?: string;
}

export interface AskResponse {
  answer: string;
  confidence: number;
  sources: ApiSource[];
  used_model: string;
}

export interface ChatThread {
  id: string;
  user_id?: string;
  repo_id?: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ThreadMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  sources?: ApiSource[];
  used_model?: string;
  created_at: string;
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

export interface RepoMetadata {
  name: string;
  owner: string;
  default_branch: string;
  languages: Record<string, number>;
  frameworks: string[];
  dependencies: Record<string, string>;
  repository_size: number;
  file_count: number;
  directory_count: number;
  entry_points: string[];
  config_files: string[];
  technology_stack: string[];
  tree: any;
}

export interface RepoResponse {
  id: string;
  type: string;
  label: string;
  source_url: string;
  metadata: RepoMetadata;
}

export interface RepoImportRequest {
  repo_url: string;
  branch?: string;
}

export interface CommitAnalyzeRequest {
  commit_hash: string;
  commit_message: string;
  diff_text?: string;
  author?: string;
  repo_id?: string;
}

export interface CommitAnalyzeResponse {
  commit_hash: string;
  summary: string;
  impact_level: "high" | "medium" | "low";
  affected_services: string[];
  risk_factors: string[];
  suggested_reviewers: string[];
  node_id?: string;
}

export interface OnboardingSection {
  title: string;
  content: string;
  items: string[];
}

export interface OnboardingGuideRequest {
  repo_id: string;
  role?: string;
}

export interface OnboardingGuideResponse {
  repo_id: string;
  role: string;
  overview: string;
  tech_stack: string[];
  entry_points: string[];
  key_decisions: string[];
  sections: OnboardingSection[];
}

export interface TimelineEvent {
  id: string;
  type: string;
  title: string;
  description?: string;
  timestamp: string;
  author?: string;
  source_url?: string;
  tags: string[];
  impact_level?: string;
}

export interface TimelineResponse {
  scope: string;
  scope_type: string;
  total_events: number;
  events: TimelineEvent[];
}
