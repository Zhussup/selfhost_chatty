// Theme preference: "light" | "dark" | "system".
//
// `system` is resolved to a concrete light/dark value and written to
// <html data-theme>, so the stylesheet needs no media queries and an explicit
// toggle still works on a machine whose OS setting disagrees with it.

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark" | "system";

const KEY = "chat.theme";
const listeners = new Set<() => void>();
let mq: MediaQueryList | null = null;

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage may be unavailable (private mode) */
  }
  return "system";
}

let current: Theme = read();

function resolve(t: Theme): "light" | "dark" {
  if (t === "light" || t === "dark") return t;
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function paint(): void {
  const resolved = resolve(current);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

function media(): MediaQueryList | null {
  if (!mq) {
    try {
      mq = window.matchMedia("(prefers-color-scheme: light)");
    } catch {
      mq = null;
    }
  }
  return mq;
}

/** Called once at boot: paint and follow the OS while the preference is `system`. */
export function applyTheme(): void {
  paint();
  media()?.addEventListener("change", () => {
    if (current === "system") paint();
  });
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    current = read();
    paint();
    listeners.forEach((l) => l());
  });
}

export function getTheme(): Theme {
  return current;
}

export function setTheme(next: Theme): void {
  current = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* ignore */
  }
  paint();
  listeners.forEach((l) => l());
}

/** Cycle light → dark → system. */
export function cycleTheme(): void {
  setTheme(current === "light" ? "dark" : current === "dark" ? "system" : "light");
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** The stored preference (a primitive, so the snapshot is stable). */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, getTheme);
}
