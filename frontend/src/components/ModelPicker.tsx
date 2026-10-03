import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import Icon from "./Icon";
import type { ModelInfo } from "../types";

function fmtSize(bytes: number): string {
  if (!bytes) return "";
  const gb = bytes / 1e9;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1e6)} MB`;
}

function subtitle(m: ModelInfo): string {
  const size = fmtSize(m.size);
  return [m.family, size].filter(Boolean).join(" · ") || "model";
}

export default function ModelPicker() {
  const paneId = usePaneId();
  const models = useStore((st) => st.models);
  const model = usePane((p) => p.model, "");
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
        <Icon name="chevronDown" size={14} className="chev" />
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
                  useStore.getState().setModel(paneId, m.name);
                  setOpen(false);
                }}
              >
                <span className="pinfo">
                  <span className="pname">{m.name}</span>
                  <span className="picker-sub">{subtitle(m)}</span>
                </span>
                {m.name === model && (
                  <span className="picker-check">
                    <Icon name="check" size={15} />
                  </span>
                )}
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
            <Icon name="refresh" size={15} /> refresh
          </button>
        </div>
      )}
    </div>
  );
}
