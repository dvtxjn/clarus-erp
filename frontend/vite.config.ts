import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // libraries in their own files: they rarely change, so after a release the browser keeps
        // its cached copy and only downloads the (small) app code again
        manualChunks(id) {
          if (id.includes('node_modules/ag-grid')) return 'ag-grid'
          if (id.includes('node_modules/react') || id.includes('node_modules/scheduler')) return 'react'
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
