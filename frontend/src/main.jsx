import React from "react";
import { createRoot } from "react-dom/client";
import ClearframeApp from "./ClearframeApp.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ClearframeApp />
  </React.StrictMode>
);
