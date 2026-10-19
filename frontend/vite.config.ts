import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중 FastAPI(8000)로 프록시
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } } },
});
