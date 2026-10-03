import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import App from "./App";
import { useStore } from "./state";
import { installPersistence } from "./persist";
import { applyTheme } from "./theme";

applyTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);

installPersistence(useStore);
useStore.getState().boot();
