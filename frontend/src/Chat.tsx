import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { askQuestion, createChatThread, deleteChatThread, getThreadMessages, listChatThreads } from "./api";
import type { ApiSource, ChatMessage, ChatThread, ToastTone } from "./types";

const examplePrompts = [
  "What changed recently?",
  "Why was gateway rate limiting added?",
  "Explain the auth architecture.",
  "Which PR likely caused the latest regression?",
];

function createMessage(
  role: ChatMessage["role"],
  content: string,
  extra?: Partial<Omit<ChatMessage, "id" | "role" | "content">>,
): ChatMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
    createdAt: new Date().toISOString(),
    ...extra,
  };
}

export function Chat({
  onNotify,
  repoId,
}: {
  onNotify: (tone: ToastTone, title: string, description: string) => void;
  repoId: string;
}): JSX.Element {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false);
  const [inlineError, setInlineError] = useState<string>("");
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Load chat threads on component mount
  useEffect(() => {
    let active = true;
    const fetchThreads = async (): Promise<void> => {
      try {
        const list = await listChatThreads(repoId.trim() || undefined);
        if (!active) return;
        setThreads(list);
        if (list.length > 0 && !activeThreadId) {
          setActiveThreadId(list[0].id);
        }
      } catch {
        // Silently fail if memory backend is not yet populated
      }
    };
    void fetchThreads();
    return () => {
      active = false;
    };
  }, [repoId]);

  // Load messages when activeThreadId changes
  useEffect(() => {
    if (!activeThreadId) {
      setMessages([]);
      return;
    }

    let active = true;
    const loadMessages = async (): Promise<void> => {
      setLoadingHistory(true);
      try {
        const history = await getThreadMessages(activeThreadId);
        if (!active) return;
        const mapped: ChatMessage[] = history.map((item) => ({
          id: item.id,
          role: item.role,
          content: item.content,
          createdAt: item.created_at,
          confidence: item.confidence ?? undefined,
          sources: item.sources ?? [],
          status: "ready",
        }));
        setMessages(mapped);
      } catch {
        if (!active) return;
        setMessages([]);
      } finally {
        if (active) setLoadingHistory(false);
      }
    };

    void loadMessages();
    return () => {
      active = false;
    };
  }, [activeThreadId]);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }

    textareaRef.current.style.height = "0px";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
  }, [question]);

  const hasMessages = messages.length > 0;
  const repoLabel = useMemo(() => (repoId.trim() ? repoId.trim() : "All connected engineering context"), [repoId]);

  const handleNewThread = async (): Promise<string | null> => {
    try {
      const thread = await createChatThread("New Conversation", repoId.trim() || undefined);
      setThreads((current) => [thread, ...current]);
      setActiveThreadId(thread.id);
      setMessages([]);
      return thread.id;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to create new chat thread.";
      onNotify("error", "Thread error", message);
      return null;
    }
  };

  const handleDeleteThread = async (threadId: string): Promise<void> => {
    try {
      await deleteChatThread(threadId);
      setThreads((current) => current.filter((t) => t.id !== threadId));
      if (activeThreadId === threadId) {
        const remaining = threads.filter((t) => t.id !== threadId);
        setActiveThreadId(remaining.length > 0 ? remaining[0].id : null);
        setMessages([]);
      }
      onNotify("success", "Thread deleted", "Conversation thread removed.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to delete thread.";
      onNotify("error", "Delete failed", message);
    }
  };

  const sendQuestion = async (value: string): Promise<void> => {
    const trimmed = value.trim();
    if (!trimmed || loading) {
      return;
    }

    let currentThreadId = activeThreadId;
    if (!currentThreadId) {
      currentThreadId = await handleNewThread();
    }

    const userMessage = createMessage("user", trimmed);
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setLoading(true);
    setInlineError("");

    try {
      const response = await askQuestion({
        question: trimmed,
        repo_id: repoId.trim() || undefined,
        thread_id: currentThreadId || undefined,
      });

      setMessages((current) => [
        ...current,
        createMessage("assistant", response.answer, {
          confidence: response.confidence,
          sources: response.sources,
          status: "ready",
        }),
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to complete the request.";
      setInlineError(message);
      setMessages((current) => [
        ...current,
        createMessage("assistant", message, {
          status: "error",
        }),
      ]);
      onNotify("error", "Chat request failed", message);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    await sendQuestion(question);
  };

  return (
    <section className="page chat-page">
      <div className="page-header">
        <div>
          <p className="eyebrow">Chat Assistant</p>
          <h2>Ask engineering questions against actual project memory.</h2>
        </div>
        <div className="header-meta">Current scope: {repoLabel}</div>
      </div>

      <div className="chat-layout" style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: "16px", height: "100%" }}>
        {/* Thread Sidebar */}
        <aside className="thread-sidebar" style={{ background: "rgba(255, 255, 255, 0.03)", borderRadius: "8px", padding: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
          <button
            className="button button-primary"
            style={{ width: "100%", justifyContent: "center" }}
            onClick={() => void handleNewThread()}
            type="button"
          >
            + New Thread
          </button>

          <div className="thread-list" style={{ overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: "4px", marginTop: "8px" }}>
            {threads.length === 0 ? (
              <p className="subtle" style={{ fontSize: "12px", padding: "8px" }}>No past conversations.</p>
            ) : (
              threads.map((thread) => (
                <div
                  key={thread.id}
                  className={`thread-item ${activeThreadId === thread.id ? "active" : ""}`}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    cursor: "pointer",
                    background: activeThreadId === thread.id ? "rgba(255, 255, 255, 0.1)" : "transparent",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: "13px",
                  }}
                  onClick={() => setActiveThreadId(thread.id)}
                >
                  <span style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap", flex: 1 }}>
                    {thread.title}
                  </span>
                  <button
                    style={{ background: "none", border: "none", color: "#888", cursor: "pointer", padding: "2px 4px" }}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDeleteThread(thread.id);
                    }}
                    title="Delete conversation"
                    type="button"
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Chat Main Shell */}
        <div className="chat-shell">
          <div className="chat-thread" aria-live="polite">
            {loadingHistory ? (
              <div style={{ padding: "24px", textAlign: "center" }}>Loading conversation history...</div>
            ) : !hasMessages ? (
              <div className="chat-empty-state">
                <div className="badge badge-primary">Ask DevContextIQ</div>
                <h3>Reason across changes, decisions, ADRs, and incidents.</h3>
                <p>
                  This is not code search. It is a memory layer for engineering rationale, regression context, and
                  operational history.
                </p>

                <div className="example-grid">
                  {examplePrompts.map((prompt) => (
                    <button
                      key={prompt}
                      className="example-card"
                      disabled={loading}
                      onClick={() => void sendQuestion(prompt)}
                      type="button"
                    >
                      <span className="example-label">Example</span>
                      <strong>{prompt}</strong>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="message-list">
                {messages.map((message) => (
                  <ChatBubble key={message.id} message={message} />
                ))}
                {loading ? <TypingCard /> : null}
              </div>
            )}
            <div ref={scrollAnchorRef} />
          </div>

          <form className="composer" onSubmit={(event) => void handleSubmit(event)}>
            <div className="composer-meta">
              <span className="meta-chip">
                <span className="meta-label">Repo</span>
                <span>{repoLabel}</span>
              </span>
              <span className="meta-chip">
                <span className="meta-label">Mode</span>
                <span>Persistent context memory</span>
              </span>
            </div>

            {inlineError ? (
              <div className="inline-message inline-message-error">
                <strong>Backend request failed</strong>
                <p>{inlineError}</p>
              </div>
            ) : null}

            <div className="composer-box">
              <textarea
                ref={textareaRef}
                className="composer-input"
                disabled={loading}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendQuestion(question);
                  }
                }}
                placeholder="Ask engineering questions..."
                rows={1}
                value={question}
              />
              <button className="button button-primary composer-button" disabled={loading || !question.trim()} type="submit">
                {loading ? "Sending..." : "Send"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </section>
  );
}

function ChatBubble({ message }: { message: ChatMessage }): JSX.Element {
  if (message.role === "user") {
    return (
      <div className="chat-row chat-row-user">
        <div className="chat-bubble chat-bubble-user">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="chat-row chat-row-assistant">
      <article className={`assistant-card ${message.status === "error" ? "assistant-card-error" : ""}`}>
        <div className="assistant-card-header">
          <div className="assistant-heading">
            <span className="assistant-badge">Assistant</span>
            <span className="assistant-time">
              {new Date(message.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>

          {typeof message.confidence === "number" ? (
            <span className="confidence-badge">{Math.round(message.confidence * 100)}% confidence</span>
          ) : null}
        </div>

        <div className="assistant-copy">{message.content}</div>

        {message.sources?.length ? (
          <div className="source-row">
            {message.sources.map((source) => (
              <SourceChip key={`${source.label}-${source.url ?? "local"}`} source={source} />
            ))}
          </div>
        ) : null}
      </article>
    </div>
  );
}

function SourceChip({ source }: { source: ApiSource }): JSX.Element {
  const label = source.label || source.type || "Source";

  if (source.url) {
    return (
      <a className="source-chip" href={source.url} rel="noreferrer" target="_blank">
        {label}
      </a>
    );
  }

  return <span className="source-chip">{label}</span>;
}

function TypingCard(): JSX.Element {
  return (
    <div className="chat-row chat-row-assistant">
      <div className="assistant-card">
        <div className="assistant-card-header">
          <span className="assistant-badge">Assistant</span>
        </div>
        <div className="typing-dots" aria-label="Assistant is typing">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}
