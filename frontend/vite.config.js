import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/files': 'http://localhost:8765',
      '/hosts': 'http://localhost:8765',
      '/scan-runs': 'http://localhost:8765',
      '/stats': 'http://localhost:8765',
    },
  },
  build: {
    outDir: 'dist',
  },
})
