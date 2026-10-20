import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { SocialProvider } from "./SocialContext";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SocialProvider>
      <App />
    </SocialProvider>
  </StrictMode>,
);
