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
  // derived as strings so the selectors stay referentially stable
  const activeId = useStore((st) => st.panes[st.focusedPaneId]?.sessionId ?? null);
  const openKey = useStore((st) =>
    Object.values(st.panes)
      .map((p) => p.sessionId)
      .filter((x): x is string => !!x)
      .sort()
      .join(",")
  );
  const streamingKey = useStore((st) =>
    Object.values(st.panes)
      .filter((p) => p.turn && !p.turn.done)
      .map((p) => p.turn!.session_id)
      .filter((x): x is string => !!x)
      .sort()
      .join(",")
  );
  const openIds = new Set(openKey ? openKey.split(",") : []);
  const streamingIds = new Set(streamingKey ? streamingKey.split(",") : []);
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
      <button
        className="new-chat"
        onClick={() => useStore.getState().newSession(useStore.getState().focusedPaneId)}
      >
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
              className={`session${s.id === activeId ? " active" : ""}${openIds.has(s.id) ? " open" : ""}`}
              onClick={() => useStore.getState().openInFocusedPane(s.id)}
            >
              <span className="title">{s.title}</span>
              <span className="meta">
                {fmtTime(s.updated_at)}
                {streamingIds.has(s.id) && <span className="dot pulse" />}
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
                <button
                  title="Open in a new pane"
                  className="icon"
                  onClick={() => {
                    const st = useStore.getState();
                    const before = st.focusedPaneId;
                    st.splitPane(before, "row");
                    const created = useStore.getState().focusedPaneId;
                    // at the pane limit splitPane is a no-op — don't clobber the open pane
                    if (created !== before) st.openSession(created, s.id);
                  }}
                >
                  ⧉
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