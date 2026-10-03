import { useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../state";
import type { SessionInfo } from "../types";
import Icon from "./Icon";
import ThemeToggle from "./ThemeToggle";

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

interface Group {
  label: string;
  items: SessionInfo[];
}

/** Today / Previous 7 days / Older — computed client-side, so it must live
 *  outside any zustand selector (a fresh array there would loop forever). */
function groupSessions(sessions: SessionInfo[], query: string): Group[] {
  const q = query.trim().toLowerCase();
  const filtered = q ? sessions.filter((s) => s.title.toLowerCase().includes(q)) : sessions;
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const todayTs = startOfToday.getTime() / 1000;
  const weekTs = todayTs - 7 * 86400;
  const groups: Group[] = [
    { label: "Today", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Older", items: [] },
  ];
  for (const s of filtered) {
    if (s.updated_at >= todayTs) groups[0].items.push(s);
    else if (s.updated_at >= weekTs) groups[1].items.push(s);
    else groups[2].items.push(s);
  }
  return groups.filter((g) => g.items.length > 0);
}

export default function Sidebar({
  collapsed,
  onToggleCollapse,
  onNavigate,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNavigate?: () => void;
}) {
  const sessions = useStore((st) => st.sessions);
  const tab = useStore((st) => st.activeTab);
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
  const [query, setQuery] = useState("");

  const groups = useMemo(() => groupSessions(sessions, query), [sessions, query]);

  const commitRename = async () => {
    const id = renaming;
    setRenaming(null);
    if (id && renameValue.trim()) {
      await useStore.getState().renameSession(id, renameValue.trim().slice(0, 120));
    }
  };

  const goto = (next: "chat" | "stats") => {
    useStore.setState({ activeTab: next });
    onNavigate?.();
  };

  const openSession = (id: string) => {
    useStore.setState({ activeTab: "chat" });
    useStore.getState().openInFocusedPane(id);
    onNavigate?.();
  };

  const newChat = () => {
    useStore.setState({ activeTab: "chat" });
    useStore.getState().newSession(useStore.getState().focusedPaneId);
    onNavigate?.();
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-name">chatty</span>
        <button
          className="icon rail-collapse"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={onToggleCollapse}
        >
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} />
        </button>
      </div>

      <nav className="rail-nav">
        <button
          className={tab === "chat" ? "rail-item active" : "rail-item"}
          title="Chat"
          onClick={() => goto("chat")}
        >
          <Icon name="chat" />
          <span className="rail-label">Chat</span>
        </button>
        <button
          className={tab === "stats" ? "rail-item active" : "rail-item"}
          title="Stats"
          onClick={() => goto("stats")}
        >
          <Icon name="chart" />
          <span className="rail-label">Stats</span>
        </button>
      </nav>

      <div className="rail-body">
        <button className="new-chat" title="New chat" onClick={newChat}>
          <Icon name="plus" />
          <span className="rail-label">New chat</span>
        </button>
        <div className="search-wrap">
          <Icon name="search" size={15} className="search-icon" />
          <input
            className="session-search"
            placeholder="Search chats…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="session-list">
          {sessions.length === 0 && <div className="muted empty">No chats yet</div>}
          {sessions.length > 0 && groups.length === 0 && (
            <div className="muted empty">No matches</div>
          )}
          {groups.map((g) => (
            <div key={g.label}>
              <div className="group-label">{g.label}</div>
              {g.items.map((s) =>
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
                    onClick={() => openSession(s.id)}
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
                        <Icon name="pencil" size={15} />
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
                          onNavigate?.();
                        }}
                      >
                        <Icon name="copy" size={15} />
                      </button>
                      <a title="Export .md" className="icon" href={api.exportUrl(s.id)}>
                        <Icon name="download" size={15} />
                      </a>
                      <button
                        title="Delete"
                        className="icon"
                        onClick={() => useStore.getState().deleteSession(s.id)}
                      >
                        <Icon name="trash" size={15} />
                      </button>
                    </div>
                  </div>
                )
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="rail-foot">
        <div className="rail-user">
          <span className="avatar">
            <Icon name="sparkle" size={13} />
          </span>
          <span className="who">Self-hosted</span>
        </div>
        <ThemeToggle />
        <button className="icon" title="Log out" onClick={() => useStore.getState().logout()}>
          <Icon name="logout" />
        </button>
      </div>
    </aside>
  );
}
