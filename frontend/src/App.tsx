import { useEffect } from "react";
import Login from "./components/Login";
import Chat from "./components/Chat";
import Dashboard from "./components/Dashboard";
import { useStore } from "./state";

export default function App() {
  const booted = useStore((st) => st.booted);
  const loggedIn = useStore((st) => st.loggedIn);

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

  return (
    <div className="app">
      <nav className="tabs">
        <TabButton tab="chat" label="Chat" />
        <TabButton tab="stats" label="Stats" />
        <div className="grow" />
        <button className="tab quiet" onClick={() => useStore.getState().logout()}>
          Log out
        </button>
      </nav>
      <main className="content">
        <TabBody />
      </main>
    </div>
  );
}

function TabButton({ tab, label }: { tab: "chat" | "stats"; label: string }) {
  const active = useStore((st) => st.activeTab === tab);
  return (
    <button
      className={active ? "tab active" : "tab"}
      onClick={() => useStore.setState({ activeTab: tab })}
    >
      {label}
    </button>
  );
}

function TabBody() {
  const tab = useStore((st) => st.activeTab);
  return tab === "stats" ? <Dashboard /> : <Chat />;
}