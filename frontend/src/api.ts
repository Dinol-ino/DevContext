import type {
  ApiSource,
  AskRequest,
  AskResponse,
  GovernanceConflict,
  GovernanceRequest,
  GovernanceResponse,
  HealthResponse,
  IncidentRequest,
  IncidentResponse,
} from "./types";

const API_TIMEOUT_MS = 15000;
const API_PREFIX = "/api/v1";
const LOCAL_BACKEND_ORIGIN = "http://127.0.0.1:8000";
const PRODUCTION_BACKEND_ORIGIN = "https://devcontext-backend-agents.onrender.com";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);

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
  const defaultOrigin =
    typeof window !== "undefined" && LOCAL_HOSTS.has(window.location.hostname)
      ? LOCAL_BACKEND_ORIGIN
      : PRODUCTION_BACKEND_ORIGIN;
  const chosenBase = configuredBase || defaultOrigin;
  const normalizedBase = stripTrailingSlash(chosenBase);

  if (normalizedBase.endsWith(API_PREFIX)) {
    return normalizedBase;
  }

  return joinUrl(normalizedBase, API_PREFIX);
}

export const apiBaseUrl = resolveApiBaseUrl();

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

  if (status >= 500) {
    return "The backend returned an internal error. Try again in a moment.";
  }

  if (status === 404) {
    return "The requested backend route was not found.";
  }

  return `Request failed with status ${status}.`;
}

async function request<TResponse>(path: string, init: RequestInit = {}): Promise<TResponse> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const url = joinUrl(apiBaseUrl, path);

  try {
    const response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.headers ?? {}),
      },
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
      throw new Error("The backend did not respond in time. It may be waking up on Render.");
    }

    if (error instanceof TypeError) {
      throw new Error(`Unable to reach the backend at ${apiBaseUrl}. Check the API base URL and CORS settings.`);
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
