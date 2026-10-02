import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "highlight.js/styles/github-dark.css";
import "./styles.css";
import App from "./App";
import { useStore } from "./state";
import { installPersistence } from "./persist";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);

installPersistence(useStore);
useStore.getState().boot();