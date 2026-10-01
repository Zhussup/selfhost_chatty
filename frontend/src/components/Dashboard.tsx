import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { useStore } from "../state";
import type { DayPoint, SessionStat, StatsSummary, ToolStat, TopModel } from "../types";

const fmt = (n: number) => n.toLocaleString("en-US");

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function Dashboard() {
  const [summary, setSummary] = useState<StatsSummary | null>(null);
  const [series, setSeries] = useState<DayPoint[]>([]);
  const [topModels, setTopModels] = useState<TopModel[]>([]);
  const [tools, setTools] = useState<ToolStat[]>([]);
  const [sessions, setSessions] = useState<SessionStat[]>([]);
  const [failed, setFailed] = useState(false);

  const reload = async () => {
    setFailed(false);
    try {
      const [s, ts, tm, t, ss] = await Promise.all([
        api.statsSummary(),
        api.statsTimeseries(30),
        api.statsTopModels(),
        api.statsTools(),
        api.statsSessions(),
      ]);
      setSummary(s);
      setSeries(ts);
      setTopModels(tm);
      setTools(t);
      setSessions(ss);
    } catch {
      setFailed(true);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  if (failed) {
    return (
      <div className="dash">
        <p className="muted">failed to load stats — <button onClick={reload}>retry</button></p>
      </div>
    );
  }

  return (
    <div className="dash">
      <header className="dash-head">
        <h1>Stats</h1>
        <button className="pill" onClick={reload}>⟳ refresh</button>
      </header>

      <div className="tiles">
        <Tile label="requests" value={fmt(summary?.requests ?? 0)} sub={`${fmt(summary?.requests_failed ?? 0)} failed`} />
        <Tile label="prompt tokens" value={fmtTokens(summary?.prompt_tokens ?? 0)} sub={`${fmtTokens(summary?.cached_tokens ?? 0)} cached`} />
        <Tile label="completion tokens" value={fmtTokens(summary?.completion_tokens ?? 0)} />
        <Tile label="sessions" value={fmt(summary?.sessions ?? 0)} sub={`${fmt(summary?.user_messages ?? 0)} messages`} />
        <Tile label="tool calls" value={fmt(summary?.tool_calls ?? 0)} sub={`${summary?.days_active ?? 0} active days`} />
      </div>

      <section className="card">
        <h2>Tokens per day · last 30 days</h2>
        {series.length === 0 ? (
          <p className="muted">no requests yet — chat a little and come back</p>
        ) : (
          <div className="chart-box">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={series} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={shortDay} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(v: number) => fmtTokens(v)} />
                <Tooltip
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--fg)" }}
                  formatter={(value, name) => [fmt(Number(value)), String(name)]}
                />
                <Legend />
                <Bar dataKey="prompt" stackId="t" fill="var(--chart-1)" name="prompt" radius={[0, 0, 0, 0]} />
                <Bar dataKey="completion" stackId="t" fill="var(--chart-2)" name="completion" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      <div className="dash-cols">
        <section className="card">
          <h2>Top models · by tokens</h2>
          {topModels.length === 0 && <p className="muted">—</p>}
          <table className="tbl">
            <thead>
              <tr>
                <th>model</th>
                <th className="num">reqs</th>
                <th className="num">in</th>
                <th className="num">out</th>
              </tr>
            </thead>
            <tbody>
              {topModels.map((m) => (
                <tr key={m.model}>
                  <td className="mono">{m.model}</td>
                  <td className="num">{m.requests}</td>
                  <td className="num">{fmtTokens(m.prompt)}</td>
                  <td className="num">{fmtTokens(m.completion)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h2>Tool usage</h2>
          {tools.length === 0 && <p className="muted">—</p>}
          <table className="tbl">
            <thead>
              <tr>
                <th>tool</th>
                <th className="num">calls</th>
                <th className="num">ok</th>
                <th className="num">avg ms</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.name}>
                  <td className="mono">{t.name}</td>
                  <td className="num">{t.calls}</td>
                  <td className="num">{t.ok_rate}%</td>
                  <td className="num">{Math.round(t.avg_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card">
        <h2>Sessions · by tokens</h2>
        {sessions.length === 0 && <p className="muted">—</p>}
        <table className="tbl">
          <thead>
            <tr>
              <th>session</th>
              <th>model</th>
              <th className="num">reqs</th>
              <th className="num">in+out</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr
                key={s.id}
                onClick={() => {
                  useStore.setState({ activeTab: "chat" });
                  useStore.getState().openSession(s.id);
                }}
                className="row-link"
              >
                <td>{s.title}</td>
                <td className="mono dim">{s.model || "—"}</td>
                <td className="num">{s.requests}</td>
                <td className="num">{fmtTokens(s.prompt + s.completion)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

function shortDay(d: string): string {
  const [, m, dd] = d.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[parseInt(m, 10) - 1]} ${parseInt(dd, 10)}`;
}