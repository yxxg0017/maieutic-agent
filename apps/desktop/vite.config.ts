import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tauri 在固定端口加载开发服务器；生产构建产物由 Tauri 直接内嵌。
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5273,
    strictPort: true,
    host: "127.0.0.1",
  },
  build: {
    target: "safari16",
    sourcemap: false,
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
