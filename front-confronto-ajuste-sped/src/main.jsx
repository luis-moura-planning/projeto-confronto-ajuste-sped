import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./gestao.css";
import "./index.css";
import { initSessionTracker } from "./services/sessionTracker";

initSessionTracker();

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
