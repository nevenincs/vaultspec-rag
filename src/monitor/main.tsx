import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./monitor.scss";
import "@carbon/charts/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("The monitor entry point is missing.");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
