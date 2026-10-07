import { useState } from "react";
import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip from "./ToolChip";
import MsgActions from "./MsgActions";
import Icon from "./Icon";
import { entriesFromHistory } from "../export";
import type { ChipData } from "./ToolChip";
import type { MessageRow } from "../types";

function timeStr(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function Message({
  msg,
  onRetry,
  sessionTitle,
  onEdit,
}: {
  msg: MessageRow;
  onRetry?: () => void;
  /** Session title, used to name the exported answer file. */
  sessionTitle?: string;
  /** When set, the user bubble gets an edit affordance that resends the prompt. */
  onEdit?: (text: string) => void;
}) {
  // Hooks must run before the role-based early returns below.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  if (msg.role === "system") return null;

  if (msg.role === "tool") {
    const chip: ChipData = {
      id: msg.tool_call_id ?? msg.id,
      name: msg.tool_name ?? "tool",
      ok: !msg.error,
      ms: 0,
      result: msg.content,
    };
    return <ToolChip chip={chip} />;
  }

  if (msg.role === "user") {
    if (editing) {
      const save = () => {
        const text = draft.trim();
        if (!text) return;
        setEditing(false);
        onEdit?.(text);
      };
      return (
        <div className="msg user editing">
          <div className="msg-edit">
            <textarea
              className="msg-edit-input"
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setEditing(false);
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save();
              }}
            />
            <div className="msg-edit-actions">
              <span className="muted">Esc to cancel, Ctrl+Enter to resend</span>
              <button type="button" className="pill" onClick={() => setEditing(false)}>
                Cancel
              </button>
              <button type="button" className="pill primary" disabled={!draft.trim()} onClick={save}>
                Save &amp; resend
              </button>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="msg user">
        <div className="bubble">
          {msg.quote ? <div className="bubble-quote">{msg.quote}</div> : null}
          {msg.content}
        </div>
        <div className="stamp">{timeStr(msg.created_at)}</div>
        {onEdit && (
          <div className="msg-actions user-actions">
            <button
              type="button"
              className="icon"
              title="Edit & resend"
              onClick={() => {
                setDraft(msg.content);
                setEditing(true);
              }}
            >
              <Icon name="pencil" size={15} />
            </button>
          </div>
        )}
      </div>
    );
  }

  // assistant
  const errored = !!msg.error;
  return (
    <div className={`msg assistant${errored ? " errored" : ""}`}>
      <div className="msg-avatar">
        <Icon name="sparkle" size={15} />
      </div>
      <div className="msg-main">
        <ThinkingBlock text={msg.thinking ?? ""} active={false} />
        {msg.content ? (
          <Markdown text={msg.content} />
        ) : errored ? (
          <div className="md error-note">
            <Icon name="alert" size={15} />
            <span>{msg.error}</span>
          </div>
        ) : (
          <div className="md muted">(empty)</div>
        )}
        {msg.model && <div className="stamp model-stamp">{msg.model}</div>}
        <MsgActions
          copyText={msg.content}
          onRetry={onRetry}
          exportData={
            msg.content
              ? {
                  title: `${sessionTitle || "chatty"} — answer`,
                  entries: entriesFromHistory([msg]),
                }
              : undefined
          }
        />
      </div>
    </div>
  );
}
