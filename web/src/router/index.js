import { createRouter, createWebHistory } from 'vue-router'
import BlankLayout from '@/layouts/BlankLayout.vue'
import { useUserStore } from '@/stores/user'
import { useAgentStore } from '@/stores/agent'

const AppLayout = () => import('@/layouts/AppLayout.vue')

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'main',
      component: BlankLayout,
      children: [
        {
          path: '',
          name: 'Home',
          component: () => import('../views/HomeView.vue'),
          meta: { keepAlive: true, requiresAuth: false }
        }
      ]
    },
    {
      path: '/auth/oidc/callback', // oidc登录回调页面
      name: 'OIDCCallback',
      component: () => import('@/views/OIDCCallbackView.vue'),
      meta: { public: true }
    },
    {
      path: '/auth/cli/authorize',
      name: 'CLIAuthAuthorize',
      component: () => import('@/views/CLIAuthAuthorizeView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/agent',
      name: 'AgentMain',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'AgentComp',
          component: () => import('../views/AgentView.vue'),
          meta: { keepAlive: true, requiresAuth: true }
        },
        {
          path: ':thread_id',
          name: 'AgentCompWithThreadId',
          component: () => import('../views/AgentView.vue'),
          meta: { keepAlive: true, requiresAuth: true }
        }
      ]
    },
    {
      path: '/workspace',
      name: 'workspace',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'WorkspaceComp',
          component: () => import('../views/WorkspaceView.vue'),
          meta: { keepAlive: true, requiresAuth: true }
        }
      ]
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'DashboardComp',
          component: () => import('../views/DashboardView.vue'),
          meta: { keepAlive: false, requiresAuth: true, requiresSuperAdmin: true }
        }
      ]
    },
    {
      path: '/agent-manage',
      name: 'agent-manage',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'AgentManageComp',
          component: () => import('../views/AgentManageView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        },
        {
          path: 'roles',
          name: 'AgentManageRoles',
          component: () => import('../views/AgentManageView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        }
      ]
    },
    {
      path: '/scheduled-agents',
      name: 'scheduled-agents',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'ScheduledAgentsComp',
          component: () => import('../views/ScheduledAgentsView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        }
      ]
    },
    {
      path: '/workflows',
      name: 'workflows',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'WorkflowsComp',
          component: () => import('../views/WorkflowView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        },
        {
          path: 'platform',
          name: 'WorkflowsPlatform',
          component: () => import('../views/WorkflowView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        },
        {
          path: ':id',
          name: 'WorkflowEditor',
          component: () => import('../views/WorkflowEditorView.vue'),
          meta: { keepAlive: false, requiresAuth: true }
        }
      ]
    },
    {
      path: '/roles',
      name: 'roles-redirect',
      redirect: '/agent-manage/roles',
    },
    {
      path: '/extensions',
      name: 'extensions',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'ExtensionsComp',
          component: () => import('../views/ExtensionsView.vue'),
          meta: {
            keepAlive: false,
            requiresAuth: true
          },
          children: [
            {
              path: 'knowledgebase/:kbId',
              name: 'ExtensionKnowledgeBaseDetail',
              component: () => import('../views/DataBaseInfoView.vue'),
              meta: {
                keepAlive: false,
                requiresAuth: true,
                requiresAdmin: true
              }
            },
            {
              path: 'knowledgebase/:kbId/evaluation/:datasetId',
              name: 'ExtensionEvaluationBenchmarkDetail',
              component: () => import('../views/EvaluationBenchmarkDetailView.vue'),
              meta: {
                keepAlive: false,
                requiresAuth: true,
                requiresAdmin: true
              }
            }
          ]
        }
      ]
    },
    {
      path: '/skills',
      name: 'skills',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'SkillsConnectorsComp',
          component: () => import('../views/SkillsConnectorsView.vue'),
          meta: {
            keepAlive: false,
            requiresAuth: true
          },
          children: [
            {
              path: 'mcp/:slug',
              name: 'SkillMcpDetail',
              component: () => import('../components/extensions/McpDetailView.vue'),
              meta: {
                keepAlive: false,
                requiresAuth: true,
                requiresAdmin: true
              }
            },
            {
              path: 'skill/:slug',
              name: 'SkillDetail',
              component: () => import('../components/extensions/SkillDetailView.vue'),
              meta: {
                keepAlive: false,
                requiresAuth: true
              }
            }
          ]
        }
      ]
    },
    {
      path: '/marketplace',
      name: 'marketplace',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'SkillMarketComp',
          component: () => import('../components/marketplace/SkillMarketPanel.vue'),
          meta: {
            keepAlive: false,
            requiresAuth: true
          }
        }
      ]
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('../views/EmptyView.vue'),
      meta: { requiresAuth: false }
    }
  ]
})

// 全局前置守卫
router.beforeEach(async (to) => {
  // 检查路由是否需要认证
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth === true)
  const requiresAdmin = to.matched.some((record) => record.meta.requiresAdmin)
  const requiresSuperAdmin = to.matched.some((record) => record.meta.requiresSuperAdmin)

  const userStore = useUserStore()

  // 如果有 token 但用户信息未加载，先获取用户信息
  if (userStore.token && !userStore.userId) {
    try {
      await userStore.getCurrentUser()
    } catch (error) {
      // 如果获取用户信息失败（如 token 过期），清除 token
      console.error('获取用户信息失败:', error)
      userStore.logout()
    }
  }

  const isLoggedIn = userStore.isLoggedIn
  const isAdmin = userStore.isAdmin
  const isSuperAdmin = userStore.isSuperAdmin

  // 如果路由需要认证但用户未登录
  if (requiresAuth && !isLoggedIn) {
    // 保存尝试访问的路径，登录后跳转
    sessionStorage.setItem('redirect', to.fullPath)
    return '/'
  }

  // 如果路由需要管理员权限但用户不是管理员
  if (requiresAdmin && !isAdmin) {
    // 如果是普通用户，跳转到聊天页空态
    try {
      const agentStore = useAgentStore()
      // 等待 store 初始化完成
      if (!agentStore.isInitialized) {
        await agentStore.initialize()
      }
      return '/agent'
    } catch (error) {
      console.error('获取智能体信息失败:', error)
      return '/agent'
    }
  }

  // 如果路由需要超级管理员权限但用户不是超级管理员
  if (requiresSuperAdmin && !isSuperAdmin) {
    try {
      const agentStore = useAgentStore()
      if (!agentStore.isInitialized) {
        await agentStore.initialize()
      }
      return '/agent'
    } catch (error) {
      console.error('获取智能体信息失败:', error)
      return '/agent'
    }
  }

  // 其他情况正常导航
  return true
})

export default router
