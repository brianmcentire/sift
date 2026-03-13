import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/client-host': 'http://localhost:8765',
      '/directories': 'http://localhost:8765',
      '/files': 'http://localhost:8765',
      '/hosts': 'http://localhost:8765',
      '/maintenance': 'http://localhost:8765',
      '/scan-runs': 'http://localhost:8765',
      '/stats': 'http://localhost:8765',
      '/tree': 'http://localhost:8765',
    },
  },
  build: {
    outDir: 'dist',
  },
})
