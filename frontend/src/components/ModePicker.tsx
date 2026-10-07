import { useEffect, useRef, useState } from "react";
import { usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import { modeById } from "../modes";
import Icon from "./Icon";

/**
 * The persona selector, in the composer bar next to tools/think.
 *
 * The menu opens upward (`.mode-menu` is anchored to the bottom of the button)
 * because the composer sits at the bottom of the pane. Dismissal follows
 * ModelPicker: a document mousedown outside the wrapper closes it.
 */
export default function ModePicker() {
  const paneId = usePaneId();
  const modes = useStore((st) => st.modes);
  const modeId = usePane((p) => p.mode, "assistant");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = modeById(modes, modeId);
  // With the registry unavailable the picker still shows which mode is active,
  // it just cannot offer a list.
  const label = current?.title ?? modeId;
  const active = modeId !== "assistant";

  return (
    <div className="mode-picker" ref={ref}>
      <button
        type="button"
        className={open || active ? "icon on" : "icon"}
        title="Chat mode"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="mode-icon">{current?.icon ?? "🤖"}</span>
        <span className="hide-narrow">{label}</span>
        <Icon name="chevronDown" size={12} />
      </button>
      {open && (
        <div className="mode-menu">
          {modes.length === 0 && <div className="muted empty">modes unavailable</div>}
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              className={m.id === modeId ? "picker-item active" : "picker-item"}
              onClick={() => {
                setOpen(false);
                useStore.getState().requestMode(paneId, m.id);
              }}
            >
              <span className="mode-icon">{m.icon}</span>
              <span className="pinfo">
                <span className="pname">{m.title}</span>
                <span className="picker-sub">{m.hint}</span>
              </span>
              {m.id === modeId && (
                <span className="picker-check">
                  <Icon name="check" size={15} />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
