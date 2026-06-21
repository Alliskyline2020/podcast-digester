import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import VueVirtualScroller from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

const app = createApp(App)

// 全局错误处理器：捕获组件渲染 / watcher / 生命周期里未处理的异常。
// 没有 errorHandler 时，Vue 会把错误打印到 console 但 UI 会白屏。
app.config.errorHandler = (err, _instance, info) => {
  // 生产构建里 console.log/debug/info 会被 esbuild drop，这里用 error。
  console.error('[Vue errorHandler]', info, err)
}

// 捕获未处理的 Promise rejection（比如 api.js 里漏掉 await/catch 的链）。
// 避免 "Uncaught (in promise)" 只在 console 里漂着、用户毫无感知。
window.addEventListener('unhandledrejection', (event) => {
  console.error('[unhandledrejection]', event.reason)
})

app.use(router)
app.use(VueVirtualScroller)
app.mount('#app')
