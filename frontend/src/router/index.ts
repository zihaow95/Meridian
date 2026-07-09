import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { pinia } from '@/stores'
import { useAuthStore } from '@/modules/auth/store'

import AccessDeniedView from '@/modules/auth/AccessDeniedView.vue'
import LoginView from '@/modules/auth/LoginView.vue'
import ConfigurationListView from '@/modules/admin/ConfigurationListView.vue'
import AuditListView from '@/modules/admin/AuditListView.vue'
import DocumentWorkbenchView from '@/modules/admin/DocumentWorkbenchView.vue'
import UserAccessView from '@/modules/admin/UserAccessView.vue'
import TodoListView from '@/modules/todos/TodoListView.vue'
import OpportunityListView from '@/modules/opportunities/OpportunityListView.vue'
import OpportunityCreateView from '@/modules/opportunities/OpportunityCreateView.vue'
import OpportunityWorkbenchView from '@/modules/opportunities/OpportunityWorkbenchView.vue'
import OpportunityPoolView from '@/modules/opportunities/OpportunityPoolView.vue'
import LifecycleBoardView from '@/modules/opportunities/LifecycleBoardView.vue'
import MajorGateDecisionView from '@/modules/stage-gates/MajorGateDecisionView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/todos' },
  { path: '/login', component: LoginView },
  { path: '/access-denied', component: AccessDeniedView },
  { path: '/todos', component: TodoListView, meta: { requiresAuth: true } },
  { path: '/opportunities', component: OpportunityListView, meta: { requiresAuth: true } },
  { path: '/opportunities/new', component: OpportunityCreateView, meta: { requiresAuth: true } },
  {
    path: '/opportunities/pool',
    component: OpportunityPoolView,
    meta: { requiresAuth: true },
  },
  {
    path: '/lifecycle-board',
    component: LifecycleBoardView,
    meta: { requiresAuth: true },
  },
  {
    path: '/opportunities/:publicId',
    component: OpportunityWorkbenchView,
    meta: { requiresAuth: true },
  },
  {
    path: '/stage-gates/:publicId/decide',
    component: MajorGateDecisionView,
    meta: { requiresAuth: true },
  },
  { path: '/documents/:publicId', component: AccessDeniedView, meta: { requiresAuth: true } },
  { path: '/admin/users', component: UserAccessView, meta: { requiresAuth: true } },
  { path: '/admin/configurations', component: ConfigurationListView, meta: { requiresAuth: true } },
  { path: '/admin/audit', component: AuditListView, meta: { requiresAuth: true } },
  { path: '/admin/documents', component: DocumentWorkbenchView, meta: { requiresAuth: true } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia)
  if (!to.meta.requiresAuth) return true

  if (auth.isAuthenticated) return true
  try {
    await auth.fetchMe()
    return true
  } catch {
    return { path: '/login', query: { next: to.fullPath } }
  }
})
