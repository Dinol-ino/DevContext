import type {
  AuthEventRequest,
  AuthEventResponse,
  ApiSource,
  AskRequest,
  AskResponse,
  ChatThread,
  CommitAnalyzeRequest,
  CommitAnalyzeResponse,
  GovernanceConflict,
  GovernanceRequest,
  GovernanceResponse,
  HealthResponse,
  IncidentRequest,
  IncidentResponse,
  OnboardingGuideRequest,
  OnboardingGuideResponse,
  RepoImportRequest,
  RepoResponse,
  ThreadMessage,
  TimelineEvent,
  TimelineResponse,
} from "./types";
import { getSessionToken } from "./supabase";

const API_TIMEOUT_MS = 15000;
const API_PREFIX = "/api/v1";
const RENDER_SLEEP_STATUSES = new Set([502, 503, 504]);
const ERROR_API_NOT_CONFIGURED =
  "Frontend API is not configured. Set VITE_API_BASE_URL in your deployment environment variables.";


function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function stripLeadingSlash(value: string): string {
  return value.replace(/^\/+/, "");
}

function joinUrl(base: string, path: string): string {
  return `${stripTrailingSlash(base)}/${stripLeadingSlash(path)}`;
}

function resolveApiBaseUrl(): string {
  const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!configuredBase) {
    return "";
  }

  const normalizedBase = stripTrailingSlash(configuredBase);
  if (!normalizedBase) {
    return "";
  }

  if (normalizedBase.endsWith(API_PREFIX)) {
    return normalizedBase;
  }

  return joinUrl(normalizedBase, API_PREFIX);
}

export const apiBaseUrl = resolveApiBaseUrl();
export const isApiBaseConfigured = Boolean(apiBaseUrl);

function extractErrorDetail(parsed: unknown, status: number): string {
  if (parsed && typeof parsed === "object") {
    const record = parsed as Record<string, unknown>;

    if (typeof record.detail === "string" && record.detail.trim()) {
      return record.detail;
    }

    if (typeof record.message === "string" && record.message.trim()) {
      return record.message;
    }

    if (Array.isArray(record.detail)) {
      const joined = record.detail
        .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
        .filter(Boolean)
        .join("; ");

      if (joined) {
        return joined;
      }
    }
  }

  if (RENDER_SLEEP_STATUSES.has(status)) {
    return "Backend is starting or temporarily unavailable. Wait a few seconds and retry.";
  }

  if (status >= 500) {
    return "The backend returned an internal error. Try again in a moment.";
  }

  if (status === 404) {
    return "The requested backend route was not found.";
  }

  return `Request failed with status ${status}.`;
}

async function request<TResponse>(path: string, init: RequestInit = {}): Promise<TResponse> {
  if (!isApiBaseConfigured) {
    throw new Error(ERROR_API_NOT_CONFIGURED);
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const url = joinUrl(apiBaseUrl, path);

  try {
    const token = await getSessionToken();
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init.headers as Record<string, string> ?? {}),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...init,
      headers,
      signal: controller.signal,
    });


    if (response.status === 204) {
      return null as TResponse;
    }

    const rawText = await response.text();
    let parsed: unknown = null;
    if (rawText) {
      try {
        parsed = JSON.parse(rawText);
      } catch {
        parsed = { detail: rawText };
      }
    }

    if (!response.ok) {
      throw new Error(extractErrorDetail(parsed, response.status));
    }

    return parsed as TResponse;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Backend request timed out. Render may be waking the service; retry in a few seconds.");
    }

    if (error instanceof TypeError) {
      throw new Error(
        `Unable to reach backend at ${apiBaseUrl}. Verify VITE_API_BASE_URL, Render service health, and backend CORS origins.`,
      );
    }

    throw error instanceof Error ? error : new Error("Unexpected API error.");
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function normalizeSources(value: unknown): ApiSource[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const sources: ApiSource[] = [];

  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const record = item as Record<string, unknown>;
    const label =
      (typeof record.label === "string" && record.label) ||
      (typeof record.title === "string" && record.title) ||
      (typeof record.type === "string" && record.type) ||
      "Source";

    sources.push({
      type: typeof record.type === "string" ? record.type : undefined,
      label,
      url: typeof record.url === "string" ? record.url : undefined,
    });
  }

  return sources;
}

function normalizeGovernanceConflicts(raw: Record<string, unknown>): GovernanceConflict[] {
  if (Array.isArray(raw.conflicts)) {
    const conflicts: GovernanceConflict[] = [];

    for (const item of raw.conflicts) {
      if (!item || typeof item !== "object") {
        continue;
      }

      const record = item as Record<string, unknown>;
      conflicts.push({
        decision_label:
          (typeof record.decision_label === "string" && record.decision_label) ||
          (typeof record.label === "string" && record.label) ||
          "Architecture conflict",
        decision_url: typeof record.decision_url === "string" ? record.decision_url : undefined,
        explanation:
          (typeof record.explanation === "string" && record.explanation) ||
          (typeof record.reason === "string" && record.reason) ||
          "Conflict returned by governance analysis.",
      });
    }

    return conflicts;
  }

  if (Array.isArray(raw.matched_rules)) {
    return raw.matched_rules
      .filter((value): value is string => typeof value === "string" && value.length > 0)
      .map((rule) => ({
        decision_label: rule,
        explanation:
          typeof raw.comment_text === "string" && raw.comment_text
            ? raw.comment_text
            : "Potential conflict detected against stored decisions.",
      }));
  }

  return [];
}

export async function healthCheck(): Promise<HealthResponse> {
  const raw = await request<Record<string, unknown>>("/health", {
    method: "GET",
  });

  return {
    status: typeof raw.status === "string" ? raw.status : "unknown",
    version: typeof raw.version === "string" ? raw.version : undefined,
  };
}

export async function askQuestion(payload: AskRequest): Promise<AskResponse> {
  const raw = await request<Record<string, unknown>>("/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return {
    answer: typeof raw.answer === "string" ? raw.answer : "No answer returned.",
    confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
    used_model: typeof raw.used_model === "string" ? raw.used_model : "unknown",
    sources: normalizeSources(raw.sources),
  };
}

export async function runGovernanceCheck(payload: GovernanceRequest): Promise<GovernanceResponse> {
  const raw = await request<Record<string, unknown>>("/governance/check", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const conflicts = normalizeGovernanceConflicts(raw);

  return {
    has_conflicts: typeof raw.has_conflicts === "boolean" ? raw.has_conflicts : conflicts.length > 0,
    conflicts,
    comment_text:
      typeof raw.comment_text === "string" && raw.comment_text
        ? raw.comment_text
        : conflicts.length
          ? "Potential governance conflicts detected. Review the findings before merge."
          : "No conflicts detected against stored architecture decisions.",
    safe_to_merge: typeof raw.safe_to_merge === "boolean" ? raw.safe_to_merge : conflicts.length === 0,
  };
}

export async function runIncidentAnalysis(payload: IncidentRequest): Promise<IncidentResponse> {
  const raw = await request<Record<string, unknown>>("/incident", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return {
    issue: typeof raw.issue === "string" ? raw.issue : "No issue summary returned.",
    likely_cause: typeof raw.likely_cause === "string" ? raw.likely_cause : "No likely cause returned.",
    fix_steps: Array.isArray(raw.fix_steps) ? raw.fix_steps.filter((value): value is string => typeof value === "string") : [],
    warnings: Array.isArray(raw.warnings) ? raw.warnings.filter((value): value is string => typeof value === "string") : [],
    severity: typeof raw.severity === "string" ? raw.severity : "low",
    runbook_url: typeof raw.runbook_url === "string" ? raw.runbook_url : undefined,
  };
}

export async function recordAuthEvent(payload: AuthEventRequest): Promise<AuthEventResponse> {
  const raw = await request<Record<string, unknown>>("/auth/log", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return {
    status: typeof raw.status === "string" ? raw.status : "unknown",
    event_id: typeof raw.event_id === "string" ? raw.event_id : undefined,
    event_type: typeof raw.event_type === "string" ? raw.event_type : payload.event_type,
    email: typeof raw.email === "string" ? raw.email : payload.email,
  };
}

export async function importRepository(payload: RepoImportRequest): Promise<RepoResponse> {
  return await request<RepoResponse>("/repo/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function listRepositories(): Promise<RepoResponse[]> {
  return await request<RepoResponse[]>("/repo/list", {
    method: "GET",
  });
}

export async function deleteRepository(repoId: string): Promise<{ status: string; id: string }> {
  return await request<{ status: string; id: string }>(`/repo/${repoId}`, {
    method: "DELETE",
  });
}

export async function createChatThread(title?: string, repoId?: string): Promise<ChatThread> {
  return await request<ChatThread>("/chat/threads", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title: title || "New Conversation", repo_id: repoId || undefined }),
  });
}

export async function listChatThreads(repoId?: string): Promise<ChatThread[]> {
  const query = repoId ? `?repo_id=${encodeURIComponent(repoId)}` : "";
  return await request<ChatThread[]>(`/chat/threads${query}`, {
    method: "GET",
  });
}

export async function getThreadMessages(threadId: string): Promise<ThreadMessage[]> {
  return await request<ThreadMessage[]>(`/chat/threads/${threadId}/messages`, {
    method: "GET",
  });
}

export async function deleteChatThread(threadId: string): Promise<{ status: string; id: string }> {
  return await request<{ status: string; id: string }>(`/chat/threads/${threadId}`, {
    method: "DELETE",
  });
}

export async function analyzeCommit(payload: CommitAnalyzeRequest): Promise<CommitAnalyzeResponse> {
  return await request<CommitAnalyzeResponse>("/commit/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getCommitHistory(repoId: string): Promise<any[]> {
  return await request<any[]>(`/commit/history/${encodeURIComponent(repoId)}`, {
    method: "GET",
  });
}

export async function generateOnboardingGuide(payload: OnboardingGuideRequest): Promise<OnboardingGuideResponse> {
  return await request<OnboardingGuideResponse>("/onboarding/guide", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getOnboardingOverview(repoId: string): Promise<any> {
  return await request<any>(`/onboarding/overview/${encodeURIComponent(repoId)}`, {
    method: "GET",
  });
}

export async function getRepoTimeline(repoId: string): Promise<TimelineResponse> {
  return await request<TimelineResponse>(`/timeline/${encodeURIComponent(repoId)}`, {
    method: "GET",
  });
}

export async function getServiceTimeline(serviceName: string): Promise<TimelineResponse> {
  return await request<TimelineResponse>(`/timeline/service/${encodeURIComponent(serviceName)}`, {
    method: "GET",
  });
}
