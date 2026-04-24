import { useEffect, useState, type FormEvent } from "react";

import { apiBaseUrl, healthCheck, runGovernanceCheck, runIncidentAnalysis } from "./api";
import { Chat } from "./Chat";
import {
  getCurrentUser,
  isSupabaseConfigured,
  signOutUser,
  subscribeToAuthChanges,
  supabaseUrl,
  signInWithEmail,
  signUpWithEmail,
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

function buildHealthState(status: string, version?: string, overrides?: Partial<BackendHealth>): BackendHealth {
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
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function App(): JSX.Element {
  const [activeView, setActiveView] = useState<NavKey>("chat");
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [authMode, setAuthMode] = useState<AuthMode>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [toasts, setToasts] = useState<AppToast[]>([]);
  const [health, setHealth] = useState<BackendHealth>({ state: "checking", label: statusLabels.checking });

  // Email Auth States
  const [isRegistering, setIsRegistering] = useState<boolean>(false);
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedRepo = window.localStorage.getItem(REPO_STORAGE_KEY) ?? "";
    setSelectedRepo(storedRepo);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(REPO_STORAGE_KEY, selectedRepo);
  }, [selectedRepo]);

  useEffect(() => {
    let isMounted = true;

    const initializeAuth = async (): Promise<void> => {
      if (isSupabaseConfigured) {
        const user = await getCurrentUser();
        if (!isMounted) return;

        if (user) {
          setAuthMode("supabase");
          setCurrentUser(user);
        }
      }
      if (isMounted) setAuthLoading(false);
    };

    void initializeAuth();

    const unsubscribe = subscribeToAuthChanges((user) => {
      if (!isMounted || !user) return;
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
    setHealth({ state: "checking", label: statusLabels.checking });
    try {
      const response = await healthCheck();
      setHealth(buildHealthState(response.status, response.version));
    } catch (firstError) {
      setHealth({ state: "checking", label: "Waking backend...", error: firstError instanceof Error ? firstError.message : "Failed." });
    }
  };

  useEffect(() => {
    let cancelled = false;
    const initializeHealth = async (): Promise<void> => {
      if (cancelled) return;
      await runHealthCheck(false);
    };
    void initializeHealth();
    return () => { cancelled = true; };
  }, []);

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      pushToast("error", "Details required", "Please enter both email and password.");
      return;
    }

    try {
      const result = isRegistering 
        ? await signUpWithEmail(email, password)
        : await signInWithEmail(email, password);

      if (!result.ok) {
        pushToast("error", "Authentication failed", result.error || "An error occurred.");
        return;
      }

      pushToast("success", isRegistering ? "Account created" : "Welcome back", "You are now logged in.");
    } catch (error) {
      pushToast("error", "Authentication failed", "An unexpected error occurred.");
    }
  };

  const handleSignOut = async (): Promise<void> => {
    await signOutUser();
    setAuthMode(null);
    setCurrentUser(null);
    setEmail("");
    setPassword("");
    pushToast("info", "Signed out", "Your session has been cleared.");
  };

  if (authLoading) {
    return (
      <div className="auth-shell">
        <div className="auth-card auth-loading-card">
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
            <h1 className="auth-title" style={{ marginBottom: "1rem" }}>
              Engineering memory,
              <span> structured for decisions.</span>
            </h1>
            <p className="auth-copy" style={{ marginBottom: "2rem" }}>
              Ask what changed, recover architectural rationale, analyze merge risk, and turn incidents into reusable operating knowledge.
            </p>

            <form onSubmit={handleEmailAuth} style={{ display: "flex", flexDirection: "column", gap: "1rem", maxWidth: "24rem", margin: "0 auto" }}>
              <div className="field-group" style={{ textAlign: "left" }}>
                <label className="field-label">Email Address</label>
                <input 
                  type="email" 
                  className="input" 
                  placeholder="you@company.com"
                  value={email} 
                  onChange={(e) => setEmail(e.target.value)} 
                />
              </div>
              <div className="field-group" style={{ textAlign: "left" }}>
                <label className="field-label">Password</label>
                <input 
                  type="password" 
                  className="input" 
                  placeholder="••••••••"
                  value={password} 
                  onChange={(e) => setPassword(e.target.value)} 
                />
              </div>

              <button className="button button-primary button-wide" type="submit" style={{ marginTop: "0.5rem" }}>
                {isRegistering ? "Create Account" : "Log In"}
              </button>
            </form>

            <button 
              className="button button-ghost" 
              onClick={() => setIsRegistering(!isRegistering)} 
              type="button"
              style={{ marginTop: "1.5rem" }}
            >
              {isRegistering ? "Already have an account? Log in" : "Need an account? Register"}
            </button>
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
          <nav className="sidebar-nav" aria-label="Primary navigation" style={{ marginTop: "1rem" }}>
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
            <button onClick={handleSignOut} style={{ background: 'transparent', border: 'none', color: 'var(--text-soft)', marginTop: '1rem', cursor: 'pointer', fontSize: '0.85rem', width: '100%', textAlign: 'left' }}>
              Log out
            </button>
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
            <div className="topbar-right"></div>
          </header>

          <main className="content-shell">
            {activeView === "chat" ? <Chat onNotify={pushToast} repoId={selectedRepo} /> : null}
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

// --- SUB-COMPONENTS ---

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
      const response = await runGovernanceCheck({ pr_url: prUrl.trim(), diff_text: diffText.trim() });
      setResult(response);
      onNotify(
        response.safe_to_merge ? "success" : "warning",
        response.safe_to_merge ? "Risk review complete" : "Conflicts detected",
        response.safe_to_merge ? "No blocking architecture conflicts were detected." : "Review the recommendation before merging.",
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
        <form className="panel form-panel" onSubmit={handleSubmit}>
          <div className="field-group">
            <label className="field-label" htmlFor="pr-url">PR URL</label>
            <input id="pr-url" className="input" onChange={(event) => setPrUrl(event.target.value)} placeholder="https://github.com/org/repo/pull/312" type="url" value={prUrl} />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="diff-text">PR Diff</label>
            <textarea id="diff-text" className="textarea textarea-large" onChange={(event) => setDiffText(event.target.value)} placeholder="Paste the full diff text here..." value={diffText} />
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
            <ErrorPanel title="Governance request failed" copy={error} />
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
                          <a className="chip-link" href={conflict.decision_url} rel="noreferrer" target="_blank">View source</a>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : <p className="muted">No violations were returned for this diff.</p>}
              </div>
            </div>
          ) : (
            <EmptyPanel eyebrow="Ready for review" title="Run a governance check on a PR diff." copy="Paste a diff to see merge safety, conflict context, and a clean reviewer comment." />
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
      const response = await runIncidentAnalysis({ alert_title: alertTitle.trim(), service_name: serviceName.trim(), error_snippet: errorSnippet.trim() });
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
        <form className="panel form-panel" onSubmit={handleSubmit}>
          <div className="field-group">
            <label className="field-label" htmlFor="alert-title">Alert Title</label>
            <input id="alert-title" className="input" onChange={(event) => setAlertTitle(event.target.value)} placeholder="Payment service spike" type="text" value={alertTitle} />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="service-name">Service Name</label>
            <input id="service-name" className="input" onChange={(event) => setServiceName(event.target.value)} placeholder="payments" type="text" value={serviceName} />
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="error-snippet">Error Snippet</label>
            <textarea id="error-snippet" className="textarea" onChange={(event) => setErrorSnippet(event.target.value)} placeholder="Too many DB connections" value={errorSnippet} />
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
            <ErrorPanel title="Incident request failed" copy={error} />
          ) : result ? (
            <div className="stack-md">
              <div className="result-header">
                <span className={`badge ${severityClass(result.severity)}`}>{result.severity} severity</span>
                {result.runbook_url ? <a className="chip-link" href={result.runbook_url} rel="noreferrer" target="_blank">Open runbook</a> : null}
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
                    {result.fix_steps.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                ) : <p className="muted">No fix steps were returned.</p>}
              </div>
            </div>
          ) : (
            <EmptyPanel eyebrow="Ready for incident input" title="Analyze a production signal." copy="Start with the alert title, service, and the strongest error snippet you have." />
          )}
        </div>
      </div>
    </section>
  );
}

function SettingsPanel({ health, onNotify, selectedRepo, setSelectedRepo }: { health: BackendHealth; onNotify: Notify; selectedRepo: string; setSelectedRepo: (value: string) => void }): JSX.Element {
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
            <label className="field-label" htmlFor="repo-selector">Repo Selector</label>
            <input id="repo-selector" className="input" onBlur={() => onNotify("success", "Repository saved", "The active repo context has been updated.")} onChange={(event) => setSelectedRepo(event.target.value)} placeholder="org/repo" type="text" value={selectedRepo} />
          </div>
          <div className="settings-meta">
            <div className="meta-chip">
              <span className="meta-label">API base</span>
              <span>{apiBaseUrl}</span>
            </div>
          </div>
        </div>

        {["GitHub Connect", "Organization Memory", "Billing", "Slack Bot"].map((title) => (
          <div key={title} className="panel placeholder-panel">
            <div className="placeholder-header">
              <strong>{title}</strong>
              <span className="badge badge-muted">Coming soon</span>
            </div>
            <p className="muted">Future-ready placeholder aligned to the product surface.</p>
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
    case "chat": return "Q";
    case "governance": return "G";
    case "incident": return "I";
    case "settings": return "S";
    default: return "D";
  }
}

function severityClass(severity: string): string {
  if (severity === "high") return "badge-danger";
  if (severity === "medium") return "badge-warning";
  return "badge-success";
}

export default App;
