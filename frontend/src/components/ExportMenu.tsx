import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";
import { useStore } from "../state";
import { downloadMarkdown, entriesToMarkdown, slugify, fileStamp, type ExportEntry } from "../export";

/** Estimated menu box, used to flip the popover up near the viewport bottom. */
const MENU_W = 208;
const MENU_H = 92;

/**
 * The download affordance: one button, then a choice of Markdown (a real file)
 * or PDF (the browser's print dialog → "Save as PDF").
 *
 * The popover is portaled to <body>, not nested in place: inside a pane it
 * would be clipped by `.msg-list`'s own scroll container. Same reason the
 * reply pill is portaled (see Pane.tsx).
 */
export default function ExportMenu({
  title,
  entries,
  className = "icon",
}: {
  title: string;
  entries: ExportEntry[];
  className?: string;
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element | null;
      // the trigger toggles itself; clicks inside the menu run their own handler
      if (t?.closest(".export-menu") || t?.closest(".export-wrap")) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    // capture phase: a scroll inside .msg-list must close it, and scroll events
    // from inner containers do not bubble
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [pos]);

  if (!entries.length) return null;

  const toggle = () => {
    if (pos) return setPos(null);
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    const below = r.bottom + 6;
    const y = below + MENU_H > window.innerHeight - 8 ? Math.max(8, r.top - MENU_H - 6) : below;
    const x = Math.min(Math.max(r.left, 8), Math.max(8, window.innerWidth - MENU_W - 8));
    setPos({ x, y });
  };

  const asMarkdown = () => {
    setPos(null);
    downloadMarkdown(`${slugify(title)}-${fileStamp()}.md`, entriesToMarkdown(title, entries));
  };

  const asPdf = () => {
    setPos(null);
    useStore.getState().printDoc(title, entries);
  };

  return (
    <div className="export-wrap">
      <button ref={btnRef} type="button" className={className} title="Download" onClick={toggle}>
        <Icon name="download" size={15} />
      </button>
      {pos &&
        createPortal(
          <div className="export-menu" style={{ left: pos.x, top: pos.y }} role="menu">
            <button type="button" className="export-item" onClick={asMarkdown}>
              <Icon name="file" size={15} />
              <span className="export-label">Markdown</span>
              <span className="export-hint">.md</span>
            </button>
            <button type="button" className="export-item" onClick={asPdf}>
              <Icon name="download" size={15} />
              <span className="export-label">PDF</span>
              <span className="export-hint">via print</span>
            </button>
          </div>,
          document.body
        )}
    </div>
  );
}
