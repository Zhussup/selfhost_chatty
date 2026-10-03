import { useEffect, useRef, useState } from "react";

// Ant Design X's typing effect (`interval: 50, step: 3` ≈ 60 chars/s), applied
// to a *real* stream: the backend delivers deltas in bursts, so this reveals
// them at a steady pace instead of letting whole paragraphs pop in at once.
//
// The hook owns no store state — `turn.text` stays a plain string that grows
// as deltas arrive; only the rendered prefix is animated.

let reduceMq: MediaQueryList | null = null;

function prefersReducedMotion(): boolean {
  try {
    if (!reduceMq) reduceMq = window.matchMedia("(prefers-reduced-motion: reduce)");
    return reduceMq.matches;
  } catch {
    return false;
  }
}

export function useTypewriter(target: string, active: boolean): string {
  const [idx, setIdx] = useState(0);
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    // Nothing to animate: show the whole text. This also flushes a backlog the
    // moment a turn ends, so an answer is never left half-typed.
    if (!active || prefersReducedMotion()) {
      setIdx(targetRef.current.length);
      return;
    }
    const id = setInterval(() => {
      setIdx((i) => {
        const len = targetRef.current.length;
        if (len < i) return 0; // a new turn in this pane — type it from scratch
        const backlog = len - i;
        // Catch up when a burst left us far behind: a fixed 3 chars per tick
        // would keep the text seconds behind the model on long answers.
        const step = backlog > 240 ? Math.ceil(backlog / 10) : 3;
        return Math.min(len, i + step);
      });
    }, 50);
    return () => clearInterval(id);
  }, [active]);

  if (prefersReducedMotion()) return target;
  return idx >= target.length ? target : target.slice(0, idx);
}
