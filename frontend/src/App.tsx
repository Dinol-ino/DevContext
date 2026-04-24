import { useEffect, useMemo, useState, type FormEvent } from "react";

import { apiBaseUrl, healthCheck, runGovernanceCheck, runIncidentAnalysis } from "./api";
import { Chat } from "./Chat";
import {
  getCurrentUser,
  isSupabaseConfigured,
  signInWithGoogle,
  signOutUser,
  subscribeToAuthChanges,
  supabaseUrl,
} from "./supabase";
import type {
  AppToast,
  AuthMode,
  BackendHealth,
  GovernanceResponse,
  IncidentResponse,
  NavKey,
  ToastTone,
  UserProfile,
} from "./types";

const GUEST_STORAGE_KEY = "devcontextiq:guest-mode";
const REPO_STORAGE_KEY = "devcontextiq:selected-repo";
const HEALTH_RETRY_DELAY_MS = 2000;

const navItems: Array<{ key: NavKey; label: string; description: string }> = [
  { key: "chat", label: "Chat Assistant", description: "Engineering memory search" },
  { key: "governance", label: "Governance Check", description: "Merge risk review" },
  { key: "incident", label: "Incident Analysis", description: "Operational diagnosis" },
  { key: "settings", label: "Settings", description: "Integrations and workspace" },
];

const statusLabels: Record<BackendHealth["state"], string> = {
  healthy: "Backend healthy",
  degraded: "Backend degraded",
  checking: "Checking backend",
};

const searchPlaceholders: Record<NavKey, string> = {
  chat: "Search conversations, decisions, ADRs",
  governance: "Search merge analysis context",
  incident: "Search incident notes and runbooks",
  settings: "Search settings",
};

const createGuestUser = (): UserProfile => ({
  id: "guest-demo",
  email: "guest@demo.devcontextiq",
  fullName: "Guest Demo",
  avatarUrl: null,
});

function buildHealthState(
  status: string,
  version?: string,
  overrides?: Partial<BackendHealth>,
): BackendHealth {
  const state: BackendHealth["state"] = status === "ok" ? "healthy" : "degraded";

  return {
    state,
    label: state === "healthy" ? statusLabels.healthy : statusLabels.degraded,
    version,
    checkedAt: new Date().toISOString(),
    ...overrides,
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function App(): JSX.Element {
  const [activeView, setActiveView] = useState<NavKey>("chat");
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [authMode, setAuthMode] = useState<AuthMode>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [toasts, setToasts] = useState<AppToast[]>([]);
  const [health, setHealth] = useState<BackendHealth>({
    state: "checking",
    label: statusLabels.checking,
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const storedRepo = window.localStorage.getItem(REPO_STORAGE_KEY) ?? "";
    setSelectedRepo(storedRepo);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(REPO_STORAGE_KEY, selectedRepo);
  }, [selectedRepo]);

  useEffect(() => {
    let isMounted = true;

    const hydrateGuest = (): void => {
      if (!isMounted) {
        return;
      }

      setAuthMode("guest");
      setCurrentUser(createGuestUser());
    };

    const initializeAuth = async (): Promise<void> => {
      const guestEnabled =
        typeof window !== "undefined" && window.localStorage.getItem(GUEST_STORAGE_KEY) === "1";

      if (isSupabaseConfigured) {
        const user = await getCurrentUser();
        if (!isMounted) {
          return;
        }

        if (user) {
          setAuthMode("supabase");
          setCurrentUser(user);
        } else if (guestEnabled) {
          hydrateGuest();
        }
      } else if (guestEnabled) {
        hydrateGuest();
      }

      if (isMounted) {
        setAuthLoading(false);
      }
    };

    void initializeAuth();

    const unsubscribe = subscribeToAuthChanges((user) => {
      if (!isMounted || !user) {
        return;
      }

      if (typeof window !== "undefined") {
        window.localStorage.removeItem(GUEST_STORAGE_KEY);
      }

      setAuthMode("supabase");
      setCurrentUser(user);
      setAuthLoading(false);
    });

    return () => {
      isMounted = false;
      unsubscribe();
    };
  }, []);

  const pushToast = (tone: ToastTone, title: string, description: string): void => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((current) => [...current, { id, tone, title, description }]);

    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 4200);
  };

  const runHealthCheck = async (showToast: boolean): Promise<void> => {
    setHealth({
      state: "checking",
      label: statusLabels.checking,
    });

    try {
      const response = await healthCheck();
      setHealth(buildHealthState(response.status, response.version));

      if (showToast) {
        pushToast("success", "Backend check complete", "The API responded successfully.");
      }
      return;
    } catch (firstError) {
      setHealth({
        state: "checking",
        label: "Waking backend...",
        error: firstError instanceof Error ? firstError.message : "Initial health check failed.",
      });
    }

    await delay(HEALTH_RETRY_DELAY_MS);

    try {
      const response = await healthCheck();
      setHealth(buildHealthState(response.status, response.version));

      if (showToast) {
        pushToast("success", "Backend check complete", "The backend responded after wake-up.");
      }
    } catch (retryError) {
      setHealth({
        state: "degraded",
        label: statusLabels.degraded,
        error: retryError instanceof Error ? retryError.message : "Unable to reach backend.",
        checkedAt: new Date().toISOString(),
      });

      if (showToast) {
        pushToast("error", "Backend unavailable", retryError instanceof Error ? retryError.message : "Health check failed.");
      }
    }
  };

  useEffect(() => {
    let cancelled = false;

    const initializeHealth = async (): Promise<void> => {
      if (cancelled) {
        return;
      }

      await runHealthCheck(false);
    };

    void initializeHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  const userInitials = useMemo(() => {
    const value = currentUser?.fullName ?? currentUser?.email ?? "DC";
    const parts = value.split(" ").filter(Boolean).slice(0, 2);
    return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "DC";
  }, [currentUser]);

  const handleRefreshHealth = async (): Promise<void> => {
    await runHealthCheck(true);
  };

  const handleContinueAsGuest = (): void => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(GUEST_STORAGE_KEY, "1");
    }

    setAuthMode("guest");
    setCurrentUser(createGuestUser());
    pushToast("info", "Guest demo enabled", "You can explore the full product shell without auth.");
  };

  const handleGoogleSignIn = async (): Promise<void> => {
    const result = await signInWithGoogle();
    if (!result.ok) {
      pushToast("error", "Google sign-in unavailable", result.error ?? "Supabase auth is not configured.");
    }
  };

  const handleSignOut = async (): Promise<void> => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(GUEST_STORAGE_KEY);
    }

    await signOutUser();
    setAuthMode(null);
    setCurrentUser(null);
    pushToast("info", "Signed out", "Your session has been cleared.");
  };

  if (authLoading) {
    return (
      <div className="auth-shell">
        <div className="auth-card auth-loading-card">
          <div className="badge badge-muted">Preparing workspace</div>
          <div className="skeleton skeleton-title" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      </div>
    );
  }

  if (!currentUser || !authMode) {
    return (
      <>
        <div className="auth-shell">
          <div className="auth-card">
            <div className="badge badge-primary">DevContextIQ</div>
            <p className="eyebrow">Unified Engineering Intelligence Platform</p>
            <h1 className="auth-title">
              Engineering memory,
              <span> structured for decisions.</span>
            </h1>
            <p className="auth-copy">
              Ask what changed, recover architectural rationale, analyze merge risk, and turn incidents into reusable
              operating knowledge.
            </p>

            <div className="auth-actions">
              <button className="button button-primary" onClick={() => void handleGoogleSignIn()} type="button">
                Continue with Google
              </button>
              <button className="button button-secondary" onClick={handleContinueAsGuest} type="button">
                Continue as Guest Demo
              </button>
            </div>

            <div className="auth-footnotes">
              <div className="meta-chip">
                <span className="meta-label">Backend</span>
                <span>{health.label}</span>
              </div>
              <div className="meta-chip">
                <span className="meta-label">Auth</span>
                <span>{isSupabaseConfigured ? "Supabase ready" : "Placeholder mode"}</span>
              </div>
              <div className="meta-chip">
                <span className="meta-label">API base</span>
                <span>{apiBaseUrl}</span>
              </div>
            </div>
          </div>
        </div>
        <ToastStack toasts={toasts} />
      </>
    );
  }

  return (
    <>
      <div className="app-shell">
        <aside className={`sidebar ${isSidebarOpen ? "sidebar-open" : ""}`}>
          <div className="sidebar-header">
            <div className="logo-mark">D</div>
            <div>
              <div className="sidebar-title">DevContextIQ</div>
              <div className="sidebar-subtitle">Engineering memory</div>
            </div>
          </div>

          <nav className="sidebar-nav" aria-label="Primary navigation">
            {navItems.map((item) => (
              <button
                key={item.key}
                className={`nav-item ${item.key === activeView ? "nav-item-active" : ""}`}
                onClick={() => {
                  setActiveView(item.key);
                  setIsSidebarOpen(false);
                }}
                type="button"
              >
                <span className="nav-icon">{getNavGlyph(item.key)}</span>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <div className="workspace-card">
              <div className="workspace-title">Workspace</div>
              <div className="workspace-value">{selectedRepo || "No repository selected"}</div>
            </div>
          </div>
        </aside>

        {isSidebarOpen ? <button className="sidebar-backdrop" onClick={() => setIsSidebarOpen(false)} type="button" /> : null}

        <div className="main-shell">
          <header className="topbar">
            <div className="topbar-left">
              <button
                className="menu-button"
                onClick={() => setIsSidebarOpen((current) => !current)}
                type="button"
                aria-label="Toggle navigation"
              >
                <span />
                <span />
                <span />
              </button>

              <label className="search-shell" aria-label="Search placeholder">
                <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M10.5 4a6.5 6.5 0 1 0 4.07 11.57l4.43 4.43 1.41-1.41-4.43-4.43A6.5 6.5 0 0 0 10.5 4Zm0 2a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Z"
                    fill="currentColor"
                  />
                </svg>
                <input readOnly value={searchPlaceholders[activeView]} />
              </label>
            </div>

            <div className="topbar-right">
              <button className={`status-pill status-${health.state}`} onClick={() => void handleRefreshHealth()} type="button">
                <span className="status-dot" />
                <span>{health.label}</span>
                {health.version ? <span className="status-version">v{health.version}</span> : null}
              </button>

              <div className="profile-pill">
                {currentUser.avatarUrl ? (
                  <img alt={currentUser.fullName ?? currentUser.email} className="avatar-image" src={currentUser.avatarUrl} />
                ) : (
                  <span className="avatar-fallback">{userInitials}</span>
                )}
                <div className="profile-meta">
                  <strong>{currentUser.fullName ?? "DevContextIQ User"}</strong>
                  <small>{currentUser.email}</small>
                </div>
                <button className="button button-ghost" onClick={() => void handleSignOut()} type="button">
                  Sign out
                </button>
              </div>
            </div>
          </header>

          <main className="content-shell">
            {activeView === "chat" ? (
              <Chat onNotify={pushToast} repoId={selectedRepo} />
            ) : null}
            {activeView === "governance" ? <GovernancePanel onNotify={pushToast} /> : null}
            {activeView === "incident" ? <IncidentPanel onNotify={pushToast} /> : null}
            {activeView === "settings" ? (
              <SettingsPanel
                health={health}
                onNotify={pushToast}
                selectedRepo={selectedRepo}
                setSelectedRepo={setSelectedRepo}
              />
            ) : null}
          </main>
        </div>
      </div>

      <ToastStack toasts={toasts} />
    </>
  );
}

type Notify = (tone: ToastTone, title: string, description: string) => void;

function GovernancePanel({ onNotify }: { onNotify: Notify }): JSX.Element {
  const [prUrl, setPrUrl] = useState<string>("");
  const [diffText, setDiffText] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [result, setResult] = useState<GovernanceResponse | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (!diffText.trim()) {
      onNotify("error", "Diff required", "Paste the PR diff before running the governance check.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const response = await runGovernanceCheck({
        pr_url: prUrl.trim(),
        diff_text: diffText.trim(),
      });

      setResult(response);
      onNotify(
        response.safe_to_merge ? "success" : "warning",
        response.safe_to_merge ? "Risk review complete" : "Conflicts detected",
        response.safe_to_merge
          ? "No blocking architecture conflicts were detected."
          : "Review the recommendation before merging.",
      );
    } catch (errorValue) {
      const message = errorValue instanceof Error ? errorValue.message : "Request failed.";
      setResult(null);
      setError(message);
      onNotify("error", "Governance check failed", message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Governance Check</p>
          <h2>Analyze merge risk against existing architectural constraints.</h2>
        </div>
        <div className="header-meta">PR safety review powered by stored decisions and governance rules.</div>
      </div>

      <div className="split-layout">
        <form className="panel form-panel" onSubmit={(event) => void handleSubmit(event)}>
          <div className="field-group">
            <label className="field-label" htmlFor="pr-url">
              PR URL
            </label>
            <input
              id="pr-url"
              className="input"
              onChange={(event) => setPrUrl(event.target.value)}
              placeholder="https://github.com/org/repo/pull/312"
              type="url"
              value={prUrl}
            />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="diff-text">
              PR Diff
            </label>
            <textarea
              id="diff-text"
              className="textarea textarea-large"
              onChange={(event) => setDiffText(event.target.value)}
              placeholder="Paste the full diff text here..."
              value={diffText}
            />
          </div>

          <button className="button button-primary button-wide" disabled={loading} type="submit">
            {loading ? "Analyzing merge risk..." : "Analyze Merge Risk"}
          </button>
        </form>

        <div className="panel result-panel">
          {loading ? (
            <div className="stack-sm">
              <div className="skeleton skeleton-pill" />
              <div className="skeleton skeleton-title" />
              <div className="skeleton skeleton-line" />
              <div className="skeleton skeleton-card" />
            </div>
          ) : error ? (
            <ErrorPanel
              title="Governance request failed"
              copy={error}
            />
          ) : result ? (
            <div className="stack-md">
              <div className="result-header">
                <span className={`badge ${result.safe_to_merge ? "badge-success" : "badge-warning"}`}>
                  {result.safe_to_merge ? "Safe to merge" : "Needs review"}
                </span>
                <span className="metric-chip">{result.has_conflicts ? "Conflicts detected" : "No conflicts detected"}</span>
              </div>

              <div className="surface-block">
                <div className="surface-label">Recommendation</div>
                <p>{result.comment_text}</p>
              </div>

              <div className="surface-block">
                <div className="surface-label">Conflicts</div>
                {result.conflicts.length ? (
                  <div className="stack-sm">
                    {result.conflicts.map((conflict) => (
                      <div key={`${conflict.decision_label}-${conflict.decision_url ?? "inline"}`} className="list-row">
                        <div>
                          <strong>{conflict.decision_label}</strong>
                          <p>{conflict.explanation}</p>
                        </div>
                        {conflict.decision_url ? (
                          <a className="chip-link" href={conflict.decision_url} rel="noreferrer" target="_blank">
                            View source
                          </a>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No violations were returned for this diff.</p>
                )}
              </div>

              <div className="surface-block">
                <div className="surface-label">Comment Preview</div>
                <pre className="comment-preview">{result.comment_text}</pre>
              </div>
            </div>
          ) : (
            <EmptyPanel
              eyebrow="Ready for review"
              title="Run a governance check on a PR diff."
              copy="Paste a diff to see merge safety, conflict context, and a clean reviewer comment."
            />
          )}
        </div>
      </div>
    </section>
  );
}

function IncidentPanel({ onNotify }: { onNotify: Notify }): JSX.Element {
  const [alertTitle, setAlertTitle] = useState<string>("");
  const [serviceName, setServiceName] = useState<string>("");
  const [errorSnippet, setErrorSnippet] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [result, setResult] = useState<IncidentResponse | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (!alertTitle.trim()) {
      onNotify("error", "Alert title required", "Provide the incident alert title to continue.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const response = await runIncidentAnalysis({
        alert_title: alertTitle.trim(),
        service_name: serviceName.trim(),
        error_snippet: errorSnippet.trim(),
      });

      setResult(response);
      onNotify("success", "Incident analysis complete", "Structured remediation guidance is ready.");
    } catch (errorValue) {
      const message = errorValue instanceof Error ? errorValue.message : "Request failed.";
      setResult(null);
      setError(message);
      onNotify("error", "Incident analysis failed", message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Incident Analysis</p>
          <h2>Turn alerts into action with structured incident context.</h2>
        </div>
        <div className="header-meta">Use production signals, stack traces, or pager snippets from the live event.</div>
      </div>

      <div className="split-layout">
        <form className="panel form-panel" onSubmit={(event) => void handleSubmit(event)}>
          <div className="field-group">
            <label className="field-label" htmlFor="alert-title">
              Alert Title
            </label>
            <input
              id="alert-title"
              className="input"
              onChange={(event) => setAlertTitle(event.target.value)}
              placeholder="Payment service spike"
              type="text"
              value={alertTitle}
            />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="service-name">
              Service Name
            </label>
            <input
              id="service-name"
              className="input"
              onChange={(event) => setServiceName(event.target.value)}
              placeholder="payments"
              type="text"
              value={serviceName}
            />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="error-snippet">
              Error Snippet
            </label>
            <textarea
              id="error-snippet"
              className="textarea"
              onChange={(event) => setErrorSnippet(event.target.value)}
              placeholder="Too many DB connections"
              value={errorSnippet}
            />
          </div>

          <button className="button button-primary button-wide" disabled={loading} type="submit">
            {loading ? "Analyzing incident..." : "Analyze Incident"}
          </button>
        </form>

        <div className="panel result-panel">
          {loading ? (
            <div className="stack-sm">
              <div className="skeleton skeleton-pill" />
              <div className="skeleton skeleton-title" />
              <div className="skeleton skeleton-line" />
              <div className="skeleton skeleton-card tall" />
            </div>
          ) : error ? (
            <ErrorPanel
              title="Incident request failed"
              copy={error}
            />
          ) : result ? (
            <div className="stack-md">
              <div className="result-header">
                <span className={`badge ${severityClass(result.severity)}`}>{result.severity} severity</span>
                {result.runbook_url ? (
                  <a className="chip-link" href={result.runbook_url} rel="noreferrer" target="_blank">
                    Open runbook
                  </a>
                ) : null}
              </div>

              <div className="surface-block">
                <div className="surface-label">Issue</div>
                <p>{result.issue}</p>
              </div>

              <div className="surface-block">
                <div className="surface-label">Likely Cause</div>
                <p>{result.likely_cause}</p>
              </div>

              <div className="surface-block">
                <div className="surface-label">Fix Steps</div>
                {result.fix_steps.length ? (
                  <ol className="ordered-list">
                    {result.fix_steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                ) : (
                  <p className="muted">No fix steps were returned.</p>
                )}
              </div>

              <div className="surface-block">
                <div className="surface-label">Warnings</div>
                {result.warnings.length ? (
                  <ul className="bullet-list">
                    {result.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No warnings returned.</p>
                )}
              </div>
            </div>
          ) : (
            <EmptyPanel
              eyebrow="Ready for incident input"
              title="Analyze a production signal."
              copy="Start with the alert title, service, and the strongest error snippet you have."
            />
          )}
        </div>
      </div>
    </section>
  );
}

function SettingsPanel({
  health,
  onNotify,
  selectedRepo,
  setSelectedRepo,
}: {
  health: BackendHealth;
  onNotify: Notify;
  selectedRepo: string;
  setSelectedRepo: (value: string) => void;
}): JSX.Element {
  return (
    <section className="page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>Prepare the workspace for production integrations.</h2>
        </div>
        <div className="header-meta">Minimal controls now, integration surface ready for the next shipping pass.</div>
      </div>

      <div className="settings-grid">
        <div className="panel">
          <div className="field-group">
            <label className="field-label" htmlFor="repo-selector">
              Repo Selector
            </label>
            <input
              id="repo-selector"
              className="input"
              onBlur={() => onNotify("success", "Repository saved", "The active repo context has been updated.")}
              onChange={(event) => setSelectedRepo(event.target.value)}
              placeholder="org/repo"
              type="text"
              value={selectedRepo}
            />
          </div>

          <div className="settings-meta">
            <div className="meta-chip">
              <span className="meta-label">Backend</span>
              <span>{health.label}</span>
            </div>
            <div className="meta-chip">
              <span className="meta-label">API base</span>
              <span>{apiBaseUrl}</span>
            </div>
            <div className="meta-chip">
              <span className="meta-label">Auth</span>
              <span>{isSupabaseConfigured ? supabaseUrl : "Configure VITE_SUPABASE_URL"}</span>
            </div>
          </div>

          {health.error ? (
            <div className="inline-message inline-message-warning">
              <strong>Backend detail</strong>
              <p>{health.error}</p>
            </div>
          ) : null}
        </div>

        {["GitHub Connect", "Organization Memory", "Billing", "Slack Bot"].map((title) => (
          <div key={title} className="panel placeholder-panel">
            <div className="placeholder-header">
              <strong>{title}</strong>
              <span className="badge badge-muted">Coming soon</span>
            </div>
            <p className="muted">
              Future-ready placeholder aligned to the product surface. The UI is in place without inventing backend
              behavior.
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function EmptyPanel({ eyebrow, title, copy }: { eyebrow: string; title: string; copy: string }): JSX.Element {
  return (
    <div className="empty-panel">
      <p className="eyebrow">{eyebrow}</p>
      <h3>{title}</h3>
      <p>{copy}</p>
    </div>
  );
}

function ErrorPanel({ title, copy }: { title: string; copy: string }): JSX.Element {
  return (
    <div className="empty-panel empty-panel-error">
      <span className="badge badge-warning">Request error</span>
      <h3>{title}</h3>
      <p>{copy}</p>
    </div>
  );
}

function ToastStack({ toasts }: { toasts: AppToast[] }): JSX.Element {
  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone}`}>
          <strong>{toast.title}</strong>
          <p>{toast.description}</p>
        </div>
      ))}
    </div>
  );
}

function getNavGlyph(key: NavKey): string {
  switch (key) {
    case "chat":
      return "Q";
    case "governance":
      return "G";
    case "incident":
      return "I";
    case "settings":
      return "S";
    default:
      return "D";
  }
}

function severityClass(severity: string): string {
  if (severity === "high") {
    return "badge-danger";
  }

  if (severity === "medium") {
    return "badge-warning";
  }

  return "badge-success";
}

export default App;
