import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { askQuestion } from "./api";
import type { ApiSource, ChatMessage, ToastTone } from "./types";

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
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [inlineError, setInlineError] = useState<string>("");
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

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

  const sendQuestion = async (value: string): Promise<void> => {
    const trimmed = value.trim();
    if (!trimmed || loading) {
      return;
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

      <div className="chat-shell">
        <div className="chat-thread" aria-live="polite">
          {!hasMessages ? (
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
              <span>Ask engineering questions</span>
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
