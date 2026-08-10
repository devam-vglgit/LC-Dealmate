import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Override with LC_API_PORT when 8000 is occupied, e.g.
//   LC_API_PORT=8001 npm --prefix frontend run dev
const apiPort = process.env.LC_API_PORT || '8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
})
