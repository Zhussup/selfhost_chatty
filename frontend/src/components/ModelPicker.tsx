import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../state";

export default function ModelPicker() {
  const models = useStore((st) => st.models);
  const model = useStore((st) => st.model);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => {
    if (open && models.length === 0) useStore.getState().loadModels();
  }, [open, models.length]);

  const filtered = models.filter((m) => m.name.toLowerCase().includes(query.toLowerCase()));
  const current = models.find((m) => m.name === model) ?? null;

  return (
    <div className="model-picker" ref={ref}>
      <button className="picker-btn" onClick={() => setOpen((v) => !v)}>
        <span className="picker-name">{current ? current.name : model || "loading models…"}</span>
        <span className="chev">▾</span>
      </button>
      {open && (
        <div className="picker-menu">
          <input
            className="picker-search"
            placeholder="Filter models…"
            value={query}
            autoFocus
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="picker-list">
            {filtered.length === 0 && <div className="muted empty">no matching models</div>}
            {filtered.map((m) => (
              <button
                key={m.name}
                className={m.name === model ? "picker-item active" : "picker-item"}
                onClick={() => {
                  useStore.getState().setModel(m.name);
                  setOpen(false);
                }}
              >
                <span>{m.name}</span>
              </button>
            ))}
          </div>
          <button
            className="picker-refresh"
            onClick={(e) => {
              e.stopPropagation();
              api.models().then(({ models: fresh }) => {
                useStore.setState({ models: fresh });
              });
            }}
          >
            ⟳ refresh
          </button>
        </div>
      )}
    </div>
  );
}