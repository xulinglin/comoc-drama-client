import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/local-storage': {
        target: 'http://8.138.207.152:18081',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/local-storage/, ''),
      },
    },
  },
})
