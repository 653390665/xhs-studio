import React from "react";
import ReactDOM from "react-dom/client";

import { AppProviders } from "./app/providers";
import { AppRouter } from "./app/router";
import "./global.css";

// Apply the persisted theme before the first paint so scoped dark/light CSS
// does not flash while React mounts.
document.documentElement.dataset.theme =
  localStorage.getItem("theme-mode") === "light" ? "light" : "dark";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppProviders>
      <AppRouter />
    </AppProviders>
  </React.StrictMode>
);
