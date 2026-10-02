// The pane id is handed down as a plain string so context changes only when a
// component moves to a different pane. All data still flows through zustand.

import { createContext, useContext, type ReactNode } from "react";
import { useStore } from "../state";
import type { Pane } from "../panes";

const PaneCtx = createContext<string | null>(null);

export function PaneProvider({ paneId, children }: { paneId: string; children: ReactNode }) {
  return <PaneCtx.Provider value={paneId}>{children}</PaneCtx.Provider>;
}

export function usePaneId(): string {
  const id = useContext(PaneCtx);
  if (id == null) throw new Error("usePane used outside a pane");
  return id;
}

/** `fallback` must be a primitive or a module-level constant (stable identity). */
export function usePane<T>(selector: (p: Pane) => T, fallback: T): T {
  const id = usePaneId();
  return useStore((st) => {
    const p = st.panes[id];
    return p ? selector(p) : fallback;
  });
}
