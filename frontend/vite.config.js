import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  // esbuild 选项位于顶层；pure 让 esbuild 把这些函数调用视为可安全移除
  // （仅在返回值未被使用时，console.log 总是如此），从而在生产构建里
  // 剔除 console.log / console.debug / console.info，保留 error/warn。
  esbuild: {
    pure: ['console.log', 'console.debug', 'console.info'],
    drop: ['debugger'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/fixtures': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2020',
    sourcemap: false,
    minify: 'esbuild',
  },
  test: {
    environment: 'happy-dom',
    globals: true,
  },
})
