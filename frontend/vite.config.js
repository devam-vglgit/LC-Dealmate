import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Third arg '' loads every var in frontend/.env, not just the VITE_ ones.
  // Resolved against this file's directory so it works whatever the cwd is.
  const env = loadEnv(mode, import.meta.dirname, '')

  const apiPort = env.LC_API_PORT || '8101'
  const uiPort = Number(env.LC_UI_PORT || 5173)

  return {
    plugins: [react()],
    server: {
      port: uiPort,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${apiPort}`,
          changeOrigin: true,
        },
      },
    },
  }
})
