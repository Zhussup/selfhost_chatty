import { useState } from "react";
import { api } from "../api";
import { useStore } from "../state";

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Sidebar() {
  const sessions = useStore((st) => st.sessions);
  const activeId = useStore((st) => st.activeSessionId);
  const turn = useStore((st) => st.turn);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const commitRename = async () => {
    const id = renaming;
    setRenaming(null);
    if (id && renameValue.trim()) {
      await useStore.getState().renameSession(id, renameValue.trim().slice(0, 120));
    }
  };

  return (
    <aside className="sidebar">
      <button className="new-chat" onClick={() => useStore.getState().newSession()}>
        + New chat
      </button>
      <div className="session-list">
        {sessions.length === 0 && <div className="muted empty">No chats yet</div>}
        {sessions.map((s) =>
          renaming === s.id ? (
            <input
              key={s.id}
              className="rename-input"
              autoFocus
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => e.key === "Enter" && commitRename()}
            />
          ) : (
            <div
              key={s.id}
              className={s.id === activeId ? "session active" : "session"}
              onClick={() => useStore.getState().openSession(s.id)}
            >
              <span className="title">{s.title}</span>
              <span className="meta">
                {fmtTime(s.updated_at)}
                {turn?.session_id === s.id && !turn.done && <span className="dot" />}
              </span>
              <div className="actions" onClick={(e) => e.stopPropagation()}>
                <button
                  title="Rename"
                  className="icon"
                  onClick={() => {
                    setRenaming(s.id);
                    setRenameValue(s.title);
                  }}
                >
                  ✎
                </button>
                <a title="Export .md" className="icon" href={api.exportUrl(s.id)}>
                  ↓
                </a>
                <button title="Delete" className="icon" onClick={() => useStore.getState().deleteSession(s.id)}>
                  ×
                </button>
              </div>
            </div>
          )
        )}
      </div>
    </aside>
  );
}