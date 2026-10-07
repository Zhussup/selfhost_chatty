import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * A small centred confirmation. Portaled to <body> so it is never clipped by a
 * pane's scroll container, and dismissed by Escape or a click on the backdrop —
 * the same conventions the export popover uses.
 *
 * The app's first modal: `.confirm-backdrop` sits above `.scrim` (z-index 55)
 * so it also covers the mobile sidebar overlay.
 */
export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Continue",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="confirm-backdrop" onMouseDown={onCancel}>
      <div
        className="confirm-card"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="confirm-title">{title}</h2>
        <p className="confirm-body">{body}</p>
        <div className="confirm-actions">
          <button type="button" className="confirm-btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className="confirm-btn primary"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
