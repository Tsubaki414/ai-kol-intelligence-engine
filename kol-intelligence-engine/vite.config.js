import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Fixed port to avoid collision with other vibecode projects on 5173.
    // strictPort: true means if 5175 is taken, fail loudly instead of silently switching.
    port: 5175,
    strictPort: true,
    host: '127.0.0.1',
    open: false,
  },
  preview: {
    port: 5175,
    strictPort: true,
  },
})
