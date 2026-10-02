import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import Pane, { focusComposer } from "./Pane";
import { useStore } from "../state";
import {
  clamp,
  type MoveDir,
  type PaneNode,
  type PaneNodeSplit,
  type SplitDir,
} from "../panes";

export default function PaneTree() {
  const root = useStore((st) => st.root);
  useHotkeys();
  return (
    <div className="panes">
      <NodeView node={root} path={[]} />
    </div>
  );
}

function NodeView({ node, path }: { node: PaneNode; path: number[] }) {
  if (node.kind === "leaf") return <Pane key={node.paneId} paneId={node.paneId} />;
  return <SplitView node={node} path={path} />;
}

function SplitView({ node, path }: { node: PaneNodeSplit; path: number[] }) {
  const box = useRef<HTMLDivElement>(null);
  const row = node.dir === "row";
  return (
    <div className={row ? "pane-split row" : "pane-split col"} ref={box}>
      {/* flex-grow ratios on zero-basis children: the divider never skews them */}
      <div className="pane-cell" style={{ flexGrow: node.ratio, flexBasis: 0 }}>
        <NodeView node={node.first} path={[...path, 0]} />
      </div>
      <Divider box={box} row={row} path={path} />
      <div className="pane-cell" style={{ flexGrow: 1 - node.ratio, flexBasis: 0 }}>
        <NodeView node={node.second} path={[...path, 1]} />
      </div>
    </div>
  );
}

function Divider({
  box,
  row,
  path,
}: {
  box: RefObject<HTMLDivElement | null>;
  row: boolean;
  path: number[];
}) {
  const [dragging, setDragging] = useState(false);

  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    setDragging(true);
    // ratio is measured against the split container, whose rect is stable
    const move = (ev: PointerEvent) => {
      const el = box.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const pct = row ? (ev.clientX - r.left) / r.width : (ev.clientY - r.top) / r.height;
      useStore.getState().setRatio(path, clamp(pct, 0.08, 0.92));
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.classList.add("resizing");
  };

  return (
    <div
      className={`divider ${row ? "row-divider" : "col-divider"}${dragging ? " dragging" : ""}`}
      onPointerDown={onPointerDown}
      onDoubleClick={() => useStore.getState().setRatio(path, 0.5)}
    />
  );
}

const SPLIT_KEYS: Record<string, SplitDir> = { e: "row", o: "col" };
const MOVE_KEYS: Record<string, MoveDir> = {
  arrowleft: "left",
  arrowright: "right",
  arrowup: "up",
  arrowdown: "down",
};

function useHotkeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey) return;
      const st = useStore.getState();
      const pane = st.focusedPaneId;
      const key = e.key.toLowerCase();
      const after = () => focusComposer(useStore.getState().focusedPaneId);

      if (key in SPLIT_KEYS) {
        e.preventDefault();
        st.splitPane(pane, SPLIT_KEYS[key]);
        after();
      } else if (key === "w") {
        e.preventDefault();
        st.closePane(pane);
        after();
      } else if (key === "d") {
        e.preventDefault();
        st.newSession(pane);
        after();
      } else if (key in MOVE_KEYS) {
        e.preventDefault();
        st.focusDir(MOVE_KEYS[key]);
        after();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
