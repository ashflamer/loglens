import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Allow any host header so the app works behind a tunnel/preview proxy.
    allowedHosts: true,
    proxy: {
      // The browser never talks to the backend directly — Vite proxies it,
      // so there's no CORS config to get wrong and no hardcoded localhost
      // in client code.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});
