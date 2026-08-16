import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backendTarget = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  const configuredPort = Number.parseInt(env.VITE_PORT || "5173", 10);
  const frontendPort = Number.isFinite(configuredPort) ? configuredPort : 5173;
  return {
    plugins: [react()],
    server: {
      // Listen on IPv4 as well as localhost IPv6 so the documented
      // http://127.0.0.1:5173 address and the API proxy are reachable.
      host: "0.0.0.0",
      port: frontendPort,
      strictPort: true,
      proxy: {
        "/api": backendTarget,
        "/health": backendTarget,
      },
    },
  };
});
