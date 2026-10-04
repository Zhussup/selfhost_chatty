import { useEffect, useState } from "react";
import Login from "./components/Login";
import Chat from "./components/Chat";
import Dashboard from "./components/Dashboard";
import Sidebar from "./components/Sidebar";
import Icon from "./components/Icon";
import PrintDoc from "./components/PrintDoc";
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
    </div>
  );
}

function TabBody() {
  const tab = useStore((st) => st.activeTab);
  return tab === "stats" ? <Dashboard /> : <Chat />;
}
