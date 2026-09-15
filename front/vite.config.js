import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev 模式下 /api 代理到本地后端，免去 CORS；后端默认 uvicorn --port 8000
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
