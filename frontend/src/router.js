import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
  },
  {
    path: '/episode/:id',
    name: 'player',
    component: () => import('@/views/PlayerView.vue'),
    props: true,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  },
})

export default router
