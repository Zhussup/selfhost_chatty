import { useEffect, useState } from "react";
import Login from "./components/Login";
import Chat from "./components/Chat";
import Dashboard from "./components/Dashboard";
import Sidebar from "./components/Sidebar";
import Icon from "./components/Icon";
import PrintDoc from "./components/PrintDoc";
import ConfirmDialog from "./components/ConfirmDialog";
import { modeById } from "./modes";
import { useStore } from "./state";

const RAIL_KEY = "chat.rail";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "0";
  } catch {
    return false;
  }
}

export default function App() {
  const booted = useStore((st) => st.booted);
  const loggedIn = useStore((st) => st.loggedIn);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    useStore.getState().boot(); // StrictMode double-run safe (idempotent)
  }, []);

  if (!booted) {
    return (
      <div className="boot">
        <div className="spinner" />
      </div>
    );
  }
  if (!loggedIn) return <Login />;

  const toggleCollapse = () =>
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem(RAIL_KEY, next ? "0" : "1");
      } catch {
        /* storage may be unavailable */
      }
      return next;
    });

  const appClass = `app${collapsed ? " collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`;

  return (
    <div className={appClass}>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={toggleCollapse}
        onNavigate={() => setMobileOpen(false)}
      />
      <button
        className="icon mobile-menu"
        title="Open sidebar"
        onClick={() => setMobileOpen(true)}
      >
        <Icon name="menu" />
      </button>
      {mobileOpen && (
        <div className="scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}
      <main className="content">
        <TabBody />
      </main>
      <PrintDoc />
      <ModeConfirm />
    </div>
  );
}

/** The mode switch waiting on a confirmation, when its target carries a warning.
 *  Lives here rather than in the picker so the welcome chips and the dropdown
 *  share one dialog; the composer mounts its own for the slash-command path,
 *  where the typed text has to survive a cancel. */
function ModeConfirm() {
  const pending = useStore((st) => st.pendingMode);
  const modes = useStore((st) => st.modes);
  const info = pending ? modeById(modes, pending.modeId) : null;
  if (!pending || !info) return null;
  return (
    <ConfirmDialog
      open
      title={`Switch to ${info.title}?`}
      body={info.warn}
      confirmLabel="Switch"
      onConfirm={() => useStore.getState().resolveMode(true)}
      onCancel={() => useStore.getState().resolveMode(false)}
    />
  );
}

function TabBody() {
  const tab = useStore((st) => st.activeTab);
  return tab === "stats" ? <Dashboard /> : <Chat />;
}
