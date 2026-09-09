<template>
  <div class="home-container">
    <!-- 加载中状态 -->
    <div v-if="isLoading" class="loading-container">
      <a-spin size="large" />
      <p class="loading-text">正在连接服务...</p>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-container">
      <a-result status="error" :title="error.title" :sub-title="error.message">
        <template #extra>
          <a-button type="primary" @click="retryLoad">重试</a-button>
          <a-button :href="docsUrl" target="_blank" rel="noopener noreferrer">常见问题</a-button>
        </template>
      </a-result>
    </div>

    <!-- 正常内容 -->
    <template v-else>
      <!-- 氛围装饰背景 -->
      <div class="ambient" aria-hidden="true">
        <span class="glow"></span>
        <span class="glow-accent"></span>
        <span class="glow-center"></span>
        <svg
          class="constellation"
          viewBox="0 0 1440 900"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <!-- 左翼星群 -->
          <g class="drift drift-a">
            <g class="edges">
              <line x1="120" y1="180" x2="240" y2="120" />
              <line x1="120" y1="180" x2="90" y2="420" />
              <line x1="240" y1="120" x2="320" y2="300" />
              <line x1="90" y1="420" x2="210" y2="540" />
              <line x1="90" y1="420" x2="60" y2="600" />
              <line x1="210" y1="540" x2="150" y2="720" />
              <line x1="60" y1="600" x2="150" y2="720" />
              <line x1="320" y1="300" x2="90" y2="420" />
            </g>
            <circle class="leaf" cx="240" cy="120" r="3" />
            <circle class="leaf" cx="320" cy="300" r="2.5" />
            <circle class="leaf" cx="90" cy="420" r="4" />
            <circle class="leaf" cx="210" cy="540" r="3" />
            <circle class="leaf" cx="60" cy="600" r="2.5" />
            <circle class="pulse-ring" cx="120" cy="180" r="6" />
            <circle class="hub" cx="120" cy="180" r="6" />
            <circle class="hub" cx="150" cy="720" r="5" />
          </g>

          <!-- 右翼星群 -->
          <g class="drift drift-b">
            <g class="edges">
              <line x1="1320" y1="200" x2="1200" y2="140" />
              <line x1="1320" y1="200" x2="1350" y2="440" />
              <line x1="1200" y1="140" x2="1120" y2="320" />
              <line x1="1350" y1="440" x2="1230" y2="560" />
              <line x1="1350" y1="440" x2="1380" y2="620" />
              <line x1="1230" y1="560" x2="1300" y2="740" />
              <line x1="1380" y1="620" x2="1300" y2="740" />
              <line x1="1120" y1="320" x2="1350" y2="440" />
            </g>
            <circle class="leaf" cx="1200" cy="140" r="3" />
            <circle class="leaf" cx="1120" cy="320" r="2.5" />
            <circle class="leaf" cx="1350" cy="440" r="4" />
            <circle class="leaf" cx="1230" cy="560" r="3" />
            <circle class="leaf" cx="1380" cy="620" r="2.5" />
            <circle class="pulse-ring" cx="1320" cy="200" r="6" />
            <circle class="hub" cx="1320" cy="200" r="6" />
            <circle class="hub" cx="1300" cy="740" r="5" />
          </g>

          <!-- 上下稀疏星群 -->
          <g class="drift drift-c">
            <g class="edges">
              <line x1="560" y1="120" x2="720" y2="190" />
              <line x1="720" y1="190" x2="880" y2="100" />
              <line x1="520" y1="780" x2="710" y2="850" />
              <line x1="710" y1="850" x2="900" y2="790" />
              <line x1="420" y1="480" x2="320" y2="300" />
              <line x1="1020" y1="470" x2="1120" y2="320" />
            </g>
            <circle class="leaf" cx="560" cy="120" r="3" />
            <circle class="leaf" cx="880" cy="100" r="3" />
            <circle class="leaf" cx="720" cy="190" r="2.5" />
            <circle class="leaf" cx="520" cy="780" r="3" />
            <circle class="leaf" cx="900" cy="790" r="3" />
            <circle class="leaf" cx="710" cy="850" r="2.5" />
            <circle class="leaf" cx="420" cy="480" r="2" />
            <circle class="leaf" cx="1020" cy="470" r="2" />
          </g>

          <!-- 信号流：知识在节点间流动 -->
          <g class="signals">
            <path class="signal" d="M120 180 L240 120 L320 300" />
            <path class="signal signal-late" d="M1320 200 L1350 440 L1230 560" />
            <path class="signal signal-slow" d="M560 120 L720 190 L880 100" />
            <path class="signal signal-slower" d="M90 420 L210 540 L150 720" />
            <path class="signal signal-late signal-slow" d="M1350 440 L1380 620 L1300 740" />
            <path class="signal signal-slower signal-late" d="M520 780 L710 850 L900 790" />
          </g>
        </svg>
      </div>

      <header class="site-header">
      </header>

      <main class="hero-section">
        <span class="hero-vignette" aria-hidden="true"></span>

        <!-- 左侧：品牌展示 -->
        <div class="hero-brand-side">
          <div class="hero-content">
            <h1 class="title reveal-up delay-1">{{ infoStore.branding.title }}</h1>
            <p v-if="infoStore.branding?.subtitle" class="hero-eyebrow reveal-up delay-2">
              {{ infoStore.branding.subtitle }}
            </p>
            <div class="subtitle-wrap reveal-up delay-2">
              <Transition name="subtitle-switch">
                <p v-if="currentSubtitle" class="subtitle" :key="currentSubtitle">
                  {{ currentSubtitle }}
                </p>
              </Transition>
            </div>
          </div>
        </div>

        <!-- 右侧：登录面板 -->
        <div class="hero-login-side">
          <div class="login-panel">
            <div class="login-bg-wrapper">
              <img :src="loginBgImage" alt="" class="login-bg-img" />
            </div>
            <div class="login-form-area">
              <div class="login-form-inner">
                <header class="login-form-header">
                  <h2 v-if="isFirstRun" class="init-title">系统初始化，请创建超级管理员</h2>
                  <p v-else class="welcome-text">欢迎登录</p>
                </header>

                <div class="login-form-body" :class="{ 'is-initializing': isFirstRun }">
                  <!-- 初始化管理单 -->
                  <div v-if="isFirstRun" class="login-form login-form--init">
                    <a-form :model="adminForm" @finish="handleInitialize" layout="vertical">
                      <a-form-item label="UID" name="uid" :rules="[
                        { required: true, message: '请输入UID' },
                        { pattern: /^[a-zA-Z0-9_]+$/, message: 'UID只能包含字母、数字和下划线' },
                        { min: 3, max: 20, message: 'UID长度必须在3-20个字符之间' }
                      ]">
                        <a-input v-model:value="adminForm.uid" placeholder="请输入UID（3-20个字符）" :maxlength="20" />
                      </a-form-item>
                      <a-form-item label="手机号（可选）" name="phone_number" :rules="[
                        { validator: async (_r, v) => {
                          if (!v || !v.trim()) return
                          if (!/^1[3-9]\d{9}$/.test(v)) throw new Error('请输入正确的手机号格式')
                        }}
                      ]">
                        <a-input v-model:value="adminForm.phone_number" placeholder="可用于登录，可不填写" :maxlength="11" />
                      </a-form-item>
                      <a-form-item label="密码" name="password" :rules="[
                        { required: true, message: '请输入密码' },
                        { min: MIN_PASSWORD_LENGTH, message: `密码至少需要 ${MIN_PASSWORD_LENGTH} 个字符` }
                      ]">
                        <a-input-password v-model:value="adminForm.password" :minlength="MIN_PASSWORD_LENGTH" />
                      </a-form-item>
                      <a-form-item label="确认密码" name="confirmPassword" :rules="[
                        { required: true, message: '请确认密码' },
                        { validator: validateConfirmPassword }
                      ]">
                        <a-input-password v-model:value="adminForm.confirmPassword" />
                      </a-form-item>
                      <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                        <a-checkbox v-model:checked="agreementAccepted">
                          登录即代表同意
                          <a class="agreement-link" :href="userAgreementUrl" target="_blank" rel="noopener noreferrer" @click.stop>《用户协议》</a>
                          <a class="agreement-link" :href="privacyPolicyUrl" target="_blank" rel="noopener noreferrer" @click.stop>《隐私协议》</a>
                        </a-checkbox>
                      </a-form-item>
                      <a-form-item>
                        <a-button type="primary" html-type="submit" :loading="loginLoading" block>创建管理员账户</a-button>
                      </a-form-item>
                    </a-form>
                  </div>

                  <!-- 登录表单 -->
                  <div v-else class="login-form">
                    <a-form :model="loginForm" @finish="handleLogin" layout="vertical">
                      <a-form-item name="loginId" :rules="[{ required: true, message: '请输入UID或手机号' }]">
                        <a-input v-model:value="loginForm.loginId" placeholder="登录账号" size="large">
                          <template #prefix><UserIcon :size="18" /></template>
                        </a-input>
                      </a-form-item>
                      <a-form-item name="password" :rules="[{ required: true, message: '请输入密码' }]">
                        <a-input-password v-model:value="loginForm.password" placeholder="密码" size="large">
                          <template #prefix><LockIcon :size="18" /></template>
                        </a-input-password>
                      </a-form-item>
                      <a-form-item v-if="captchaRequired" class="captcha-form-item">
                        <div class="captcha-row">
                          <div class="captcha-image-wrapper">
                            <img
                              v-if="captchaImageUrl"
                              :src="captchaImageUrl"
                              alt="验证码"
                              class="captcha-image"
                              @click="refreshCaptcha"
                            />
                            <div v-else class="captcha-placeholder" @click="refreshCaptcha">
                              <a-spin v-if="captchaLoading" :size="'small'" />
                              <span v-else>点击获取</span>
                            </div>
                          </div>
                          <a-button
                            size="small"
                            type="link"
                            :loading="captchaLoading"
                            @click="refreshCaptcha"
                            class="captcha-refresh"
                          >
                            刷新
                          </a-button>
                        </div>
                        <a-input
                          v-model:value="captchaAnswer"
                          placeholder="请输入验证码计算结果"
                          size="large"
                          :maxlength="10"
                          @pressEnter="handleLogin"
                          class="captcha-input"
                        />
                      </a-form-item>
                      <!-- 协议 -->
                      <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                        <a-checkbox v-model:checked="agreementAccepted">
                          我已阅读并同意
                          <a class="agreement-link" :href="userAgreementUrl" target="_blank" rel="noopener noreferrer" @click.stop>用户协议</a>
                          和
                          <a class="agreement-link" :href="privacyPolicyUrl" target="_blank" rel="noopener noreferrer" @click.stop>隐私政策</a>
                        </a-checkbox>
                      </a-form-item>
                      <a-form-item>
                        <a-button type="primary" html-type="submit" :loading="loginLoading" :disabled="isLocked" block size="large" class="login-btn">
                          <span v-if="isLocked">账户已锁定 {{ formatLockTime(lockRemainingTime) }}</span>
                          <span v-else>登录</span>
                        </a-button>
                      </a-form-item>
                    </a-form>

                    <!-- OIDC -->
                    <div v-if="oidcChecking || oidcEnabled" class="third-party-login">
                      <div class="divider"><span>或使用以下方式登录</span></div>
                      <div class="login-icons">
                        <div v-if="oidcChecking" class="login-skeleton">
                          <a-skeleton-button block size="large" :active="true" />
                        </div>
                        <a-button v-else type="default" size="large" block :loading="oidcLoading" @click="handleOIDCLogin" class="oidc-btn">
                          <span class="oidc-icon">G</span>
                          {{ oidcButtonText }}
                        </a-button>
                      </div>
                    </div>
                  </div>

                  <!-- 错误提示 -->
                  <div v-if="loginError" class="login-error-message">{{ loginError }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      <footer class="footer">
        <div class="footer-content">
          <p class="copyright">
            {{ infoStore.footer?.copyright || '© 2025 All rights reserved' }}
          </p>
        </div>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { healthApi } from '@/apis/system_api'
import { authApi } from '@/apis/auth_api'
import { message } from 'ant-design-vue'
import { User as UserIcon, Lock as LockIcon } from '@lucide/vue'
import { tryAutoStartOIDC } from '@/utils/oidcAutoStart'
import { MIN_PASSWORD_LENGTH } from '@/utils/passwordValidation'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const infoStore = useInfoStore()
const agentStore = useAgentStore()

// 加载状态
const isLoading = ref(true)
const error = ref(null)
const subtitleIndex = ref(0)
let subtitleTimer = null

// ---- 登录相关状态 ----
const isFirstRun = ref(false)
const loginLoading = ref(false)
const loginError = ref('')
const agreementAccepted = ref(false)
const oidcEnabled = ref(false)
const oidcLoading = ref(false)
const oidcChecking = ref(true)
const oidcButtonText = ref('OIDC 登录')
const isLocked = ref(false)
const lockRemainingTime = ref(0)
let lockCountdownTimer = null

// ---- 验证码状态 ----
const captchaRequired = ref(false)
const captchaId = ref('')
const captchaImageUrl = ref('')
const captchaAnswer = ref('')
const captchaLoading = ref(false)

const loginForm = reactive({ loginId: '', password: '' })
const adminForm = reactive({ uid: '', password: '', confirmPassword: '', phone_number: '' })

// 品牌 & 协议计算属性
const loginBgImage = computed(() => infoStore.organization?.login_bg || '/login-bg.jpg')
const userAgreementUrl = computed(() => infoStore.footer?.user_agreement_url?.trim() || '')
const privacyPolicyUrl = computed(() => infoStore.footer?.privacy_policy_url?.trim() || '')
const showAgreementConsent = computed(() => Boolean(userAgreementUrl.value && privacyPolicyUrl.value))

const subtitleOptions = computed(() => {
  const subtitles = infoStore.branding?.subtitles
  if (Array.isArray(subtitles)) {
    const list = subtitles
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean)
    if (list.length) {
      return list
    }
  }

  const fallback = (infoStore.branding?.subtitle || '').trim()
  return fallback ? [fallback] : []
})

const currentSubtitle = computed(() => subtitleOptions.value[subtitleIndex.value] || '')

const stopSubtitleCarousel = () => {
  if (subtitleTimer) {
    clearInterval(subtitleTimer)
    subtitleTimer = null
  }
}

const startSubtitleCarousel = () => {
  stopSubtitleCarousel()
  subtitleIndex.value = 0

  if (subtitleOptions.value.length <= 1) {
    return
  }

  subtitleTimer = setInterval(() => {
    subtitleIndex.value = (subtitleIndex.value + 1) % subtitleOptions.value.length
  }, 2800)
}

const checkHealth = async () => {
  try {
    const response = await healthApi.checkHealth()
    if (response.status !== 'ok') {
      throw new Error('服务不可用')
    }
  } catch (e) {
    error.value = {
      title: '服务连接失败',
      message: '后端服务无法响应，请检查服务是否正常运行'
    }
    throw e
  }
}

const loadData = async () => {
  isLoading.value = true
  error.value = null

  try {
    // 先检查健康状态
    await checkHealth()
    // 健康检查通过后加载配置
    await infoStore.loadInfoConfig()
    startSubtitleCarousel()
  } catch (e) {
    console.error('加载失败:', e)
    stopSubtitleCarousel()
  } finally {
    isLoading.value = false
  }
}

const retryLoad = () => {
  loadData()
}

// ---- 登录工具函数 ----
const clearLockCountdown = () => {
  if (lockCountdownTimer) {
    clearInterval(lockCountdownTimer)
    lockCountdownTimer = null
  }
}

const formatLockTime = (seconds) => {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600)
    return `${h}小时${Math.floor((seconds % 3600) / 60)}分钟`
  }
  const d = Math.floor(seconds / 86400)
  return `${d}天${Math.floor((seconds % 86400) / 3600)}小时`
}

const startLockCountdown = (remainingSeconds) => {
  clearLockCountdown()
  isLocked.value = true
  lockRemainingTime.value = remainingSeconds
  lockCountdownTimer = setInterval(() => {
    lockRemainingTime.value--
    if (lockRemainingTime.value <= 0) {
      clearLockCountdown()
      isLocked.value = false
      loginError.value = ''
    }
  }, 1000)
}

const ensureAgreementAccepted = () => {
  if (!showAgreementConsent.value || agreementAccepted.value) return true
  message.warning('请先阅读并同意《用户协议》《隐私协议》')
  return false
}

// ---- 验证码管理 ----
const revokeCaptchaImage = () => {
  if (captchaImageUrl.value && captchaImageUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(captchaImageUrl.value)
  }
  captchaImageUrl.value = ''
  captchaId.value = ''
  captchaAnswer.value = ''
}

const refreshCaptcha = async () => {
  if (!loginForm.loginId.trim()) {
    message.warning('请先输入登录账号')
    return
  }
  try {
    captchaLoading.value = true
    revokeCaptchaImage()
    const data = await authApi.generateCaptcha()
    captchaId.value = data.captchaId
    captchaImageUrl.value = data.imageUrl
  } catch (err) {
    message.error('获取验证码失败，请重试')
  } finally {
    captchaLoading.value = false
  }
}

const checkAndShowCaptcha = async () => {
  if (!loginForm.loginId.trim()) return
  try {
    const data = await authApi.checkCaptchaRequired(loginForm.loginId.trim())
    if (data.required) {
      captchaRequired.value = true
    } else {
      captchaRequired.value = false
      revokeCaptchaImage()
    }
  } catch {
    // 检查失败不影响登录流程
  }
}

// 登录账号变化时重置验证码状态
let loginIdDebounce = null
watch(() => loginForm.loginId, () => {
  clearTimeout(loginIdDebounce)
  loginIdDebounce = setTimeout(() => {
    if (captchaRequired.value) {
      captchaRequired.value = false
      revokeCaptchaImage()
    }
  }, 500)
})

// ---- 登录处理 ----
const handleLogin = async () => {
  if (isLocked.value) {
    message.warning(`账户被锁定，请等待 ${formatLockTime(lockRemainingTime.value)}`)
    return
  }
  if (!ensureAgreementAccepted()) return

  // 验证码校验
  if (captchaRequired.value) {
    if (!captchaId.value) {
      message.warning('请等待验证码加载')
      return
    }
    if (!captchaAnswer.value.trim()) {
      message.warning('请输入验证码')
      return
    }
  }

  try {
    loginLoading.value = true
    loginError.value = ''
    clearLockCountdown()

    const credentials = {
      loginId: loginForm.loginId,
      password: loginForm.password,
      ...(captchaRequired.value
        ? { captchaId: captchaId.value, captchaAnswer: captchaAnswer.value.trim() }
        : {})
    }
    await userStore.login(credentials)
    message.success('登录成功')

    const redirectPath = sessionStorage.getItem('redirect') || '/'
    sessionStorage.removeItem('redirect')

    if (redirectPath === '/') {
      try { await agentStore.initialize() } catch { /* ignore */ }
      router.push('/agent')
    } else {
      router.push(redirectPath)
    }
  } catch (err) {
    if (err.status === 423) {
      let remainingTime = 0
      if (err.headers?.get) {
        const h = err.headers.get('X-Lock-Remaining')
        if (h) remainingTime = parseInt(h)
      }
      if (!remainingTime) {
        const m = err.message?.match(/(\d+)\s*秒/)
        if (m) remainingTime = parseInt(m[1])
      }
      if (remainingTime > 0) {
        startLockCountdown(remainingTime)
        loginError.value = `由于多次登录失败，账户已被锁定 ${formatLockTime(remainingTime)}`
      } else {
        loginError.value = err.message || '账户被锁定，请稍后再试'
      }
    } else {
      loginError.value = err.message || '登录失败，请检查用户名和密码'
    }

    // 登录失败后检查是否需要显示验证码
    await checkAndShowCaptcha()

    // 如果需要验证码，刷新验证码图片
    if (captchaRequired.value) {
      await refreshCaptcha()
    }
  } finally {
    loginLoading.value = false
  }
}

// ---- OIDC ----
const handleOIDCLogin = async () => {
  if (!ensureAgreementAccepted()) return
  try {
    oidcLoading.value = true
    loginError.value = ''
    const response = await authApi.getOIDCLoginUrl()
    if (response.login_url) {
      const redirectPath = sessionStorage.getItem('redirect') || route.query.redirect || '/'
      sessionStorage.setItem('oidc_redirect', redirectPath)
      window.location.href = response.login_url
    } else {
      loginError.value = '获取 OIDC 登录地址失败'
    }
  } catch (err) {
    loginError.value = err.message || 'OIDC 登录失败，请重试'
  } finally {
    oidcLoading.value = false
  }
}

const checkOIDCConfig = async () => {
  oidcChecking.value = true
  try {
    const config = await authApi.getOIDCConfig()
    oidcEnabled.value = config.enabled
    if (config.provider_name) oidcButtonText.value = config.provider_name
    return config
  } catch {
    oidcEnabled.value = false
    return null
  } finally {
    oidcChecking.value = false
  }
}

// ---- 初始化管理员 ----
const validateConfirmPassword = async (_rule, value) => {
  if (value === '') throw new Error('请确认密码')
  if (value !== adminForm.password) throw new Error('两次输入的密码不一致')
}

const handleInitialize = async () => {
  if (!ensureAgreementAccepted()) return
  try {
    loginLoading.value = true
    loginError.value = ''
    if (adminForm.password !== adminForm.confirmPassword) {
      loginError.value = '两次输入的密码不一致'
      return
    }
    await userStore.initialize({
      uid: adminForm.uid,
      password: adminForm.password,
      phone_number: adminForm.phone_number || null
    })
    message.success('管理员账户创建成功')
    router.push('/')
  } catch (err) {
    loginError.value = err.message || '初始化失败，请重试'
  } finally {
    loginLoading.value = false
  }
}

const checkFirstRunStatus = async () => {
  try {
    isFirstRun.value = await userStore.checkFirstRun()
  } catch (err) {
    console.error('检查首次运行状态失败:', err)
    loginError.value = '系统出错，请稍后重试'
  }
}

onMounted(async () => {
  await loadData()

  // 已登录用户直接跳转
  if (userStore.isLoggedIn) {
    router.push('/agent')
    return
  }

  // 显示 OIDC 回调携带的错误
  if (route.query.oidc_error) {
    loginError.value = String(route.query.oidc_error)
  }

  await checkFirstRunStatus()

  if (!isFirstRun.value) {
    const config = await checkOIDCConfig()
    if (config?.enabled) {
      const autoStarted = await tryAutoStartOIDC(
        async () => await authApi.getOIDCLoginUrl(),
        config
      )
      if (autoStarted) return
    }
  }
})

onUnmounted(() => {
  stopSubtitleCarousel()
  clearLockCountdown()
  revokeCaptchaImage()
})
</script>

<style lang="less" scoped>
.home-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--main-900);
  background: #0a2e3d;
  position: relative;
  overflow: hidden;
}

// 加载中状态
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 1rem;

  .loading-text {
    color: var(--gray-600);
    font-size: 0.95rem;
  }
}

// 错误状态
.error-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
}

// 氛围装饰背景
.ambient {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;

  // 左侧深色区域的流动渐变层
  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(
      115deg,
      #0a2e3d 0%,
      #0f4a5e 28%,
      #0d3a4a 52%,
      #0a2e3d 76%,
      #082530 100%
    );
    background-size: 300% 300%;
    opacity: 1;
    animation: bgFlow 36s ease-in-out infinite alternate;
  }
}

.glow {
  position: absolute;
  top: -180px;
  left: 20%;
  transform: translateX(-50%);
  width: 700px;
  height: 450px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(20, 120, 130, 0.35), transparent);
  opacity: 0.7;
  animation: glowDrift 26s ease-in-out infinite alternate;
}

// 辅助色光晕
.glow-accent {
  position: absolute;
  bottom: -150px;
  right: 20%;
  width: 500px;
  height: 350px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(30, 160, 170, 0.2), transparent);
  opacity: 0.5;
  animation: glowDriftAccent 34s ease-in-out infinite alternate;
}

// 中心柔光
.glow-center {
  position: absolute;
  top: 50%;
  left: 35%;
  transform: translate(-50%, -50%);
  width: 600px;
  height: 400px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(40, 180, 190, 0.12), transparent);
  opacity: 0.6;
  pointer-events: none;
}

// 知识星图
.constellation {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.edges line {
  stroke: rgba(255, 255, 255, 0.15);
  stroke-width: 1;
}

.leaf {
  fill: rgba(255, 255, 255, 0.5);
}

.hub {
  fill: rgba(255, 255, 255, 0.7);
}

.pulse-ring {
  fill: none;
  stroke: rgba(255, 255, 255, 0.3);
  stroke-width: 1.2;
  transform-box: fill-box;
  transform-origin: center;
  animation: nodePulse 3s ease-out infinite;
}

.signals .signal {
  fill: none;
  stroke: rgba(100, 220, 220, 0.6);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-dasharray: 6 140;
  opacity: 0.9;
  animation: signalFlow 4.5s linear infinite;
}

.signal-late {
  animation-delay: 1.6s;
}

.signal-slow {
  animation-duration: 6s;
  animation-delay: 0.8s;
}

.drift-a {
  animation: driftA 26s ease-in-out infinite alternate;
}

.drift-b {
  animation: driftB 30s ease-in-out infinite alternate;
}

.drift-c {
  animation: driftC 34s ease-in-out infinite alternate;
}

// 顶部导航：无背景无边框，融入页面
.site-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 0.85rem 2.5rem;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
}

.logo {
  display: flex;
  align-items: center;
  font-weight: 600;
  color: #ffffff;
  font-size: 1.1rem;
  padding: 6px 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.04));
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.1);

  .logo-img {
    height: 2rem;
    margin-right: 0.6rem;
  }
}

// Hero — 左右分屏
.hero-section {
  position: relative;
  z-index: 1;
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  padding: 0 2.5rem;
  gap: 2rem;
  max-width: 1400px;
  margin: 0 auto;
}

// 文字背后的柔光衬底
.hero-vignette {
  display: none;
}

// 左侧品牌区
.hero-brand-side {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  color: #fff;
}

.hero-content {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 0.9rem;
  max-width: 680px;
}

// 右侧登录区
.hero-login-side {
  flex: 0 0 420px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-panel {
  width: 400px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06), 0 1px 4px rgba(0, 0, 0, 0.04);
  position: relative;
  overflow: hidden;
}

.login-bg-wrapper {
  display: none;
}

.login-form-area {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px 32px 32px;
}

.login-form-inner {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.login-form-header {
  text-align: left;
  margin-bottom: 8px;

  .welcome-text {
    font-size: 20px;
    font-weight: 600;
    color: #374151;
    margin: 0;
  }
  .init-title {
    font-size: 17px;
    font-weight: 600;
    color: #374151;
    margin: 0;
    line-height: 1.4;
  }
}

.login-form {
  :deep(.ant-input-affix-wrapper) {
    padding: 0 14px;
    border-radius: 10px;
    border-color: #e0e6ed;
    height: 46px;
    display: flex;
    align-items: center;
    &:focus-within, &:hover {
      border-color: #2ab7b7;
    }
  }
  :deep(.ant-input-affix-wrapper > input.ant-input) {
    height: 44px;
    line-height: 44px;
  }
  :deep(.ant-btn) {
    height: 46px;
    font-size: 15px;
    border-radius: 10px;
  }
  :deep(.ant-input-prefix) {
    margin-right: 8px;
    color: #9ca3af;
    display: flex;
    align-items: center;
  }
  :deep(.ant-form-item) {
    margin-bottom: 16px;
  }
}

// 验证码样式
.captcha-form-item {
  margin-bottom: 16px;
}

.captcha-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.captcha-image-wrapper {
  flex: 1;
  height: 60px;
  border-radius: 10px;
  border: 1px solid #e0e6ed;
  overflow: hidden;
  cursor: pointer;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    border-color: #2ab7b7;
  }
}

.captcha-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.captcha-placeholder {
  font-size: 13px;
  color: #9ca3af;
  cursor: pointer;
  user-select: none;

  &:hover {
    color: #2ab7b7;
  }
}

.captcha-refresh {
  flex-shrink: 0;
  font-size: 13px;
  padding: 0 4px;
}

.captcha-input {
  :deep(.ant-input) {
    border-radius: 10px;
    border-color: #e0e6ed;
    height: 46px;

    &:focus, &:hover {
      border-color: #2ab7b7;
    }
  }
}

.login-btn {
  border-radius: 999px !important;
  background: linear-gradient(135deg, #1a9e9e, #2dd4d4) !important;
  border: none !important;
  height: 48px !important;
  font-size: 16px !important;
  font-weight: 600;
  box-shadow: 0 4px 16px rgba(42, 183, 183, 0.3);
  &:hover {
    background: linear-gradient(135deg, #178e8e, #28c4c4) !important;
    box-shadow: 0 6px 20px rgba(42, 183, 183, 0.4);
  }
}

.login-form.login-form--init :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.third-party-login {
  margin-top: 8px;
  .divider {
    position: relative;
    text-align: center;
    margin: 16px 0 14px;
    &::before, &::after {
      content: '';
      position: absolute;
      top: 50%;
      width: 32%;
      height: 1px;
      background-color: #e0e6ed;
    }
    &::before { left: 0; }
    &::after { right: 0; }
    span {
      display: inline-block;
      padding: 0 10px;
      background: var(--gray-0, #fff);
      color: #9ca3af;
      font-size: 12px;
    }
  }
  .login-icons {
    :deep(.ant-btn) {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-color: #e0e6ed;
      color: #374151;
      border-radius: 10px;
      height: 46px;
      font-size: 14px;
      &:hover {
        border-color: #2ab7b7;
        color: #1a9e9e;
        background-color: rgba(42, 183, 183, 0.04);
      }
    }
  }
  .login-skeleton {
    :deep(.ant-skeleton-button) {
      width: 100% !important;
      height: 46px;
      border-radius: 10px;
    }
  }
}

.oidc-btn {
  border-radius: 10px !important;
}

.oidc-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 16px;
  font-weight: 700;
  color: #374151;
}

.agreement-form-item {
  margin-bottom: 4px;
  :deep(.ant-checkbox-wrapper) {
    font-size: 13px;
    color: #6b7280;
  }
  :deep(.ant-form-item-control-input) {
    min-height: auto;
  }
}

.agreement-link {
  color: #1a9e9e;
  &:hover { text-decoration: underline; }
}

.login-error-message {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-error-50, #fff2f0);
  border: 1px solid color-mix(in srgb, var(--color-error-500, #ff4d4f) 25%, transparent);
  border-radius: 6px;
  color: var(--color-error-700, #cf1322);
  font-size: 13px;
  text-align: center;
}

.reveal-up {
  opacity: 0;
  transform: translateY(16px);
  animation: revealUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

.reveal-up.delay-1 {
  animation-delay: 120ms;
}

.reveal-up.delay-2 {
  animation-delay: 240ms;
}

.reveal-up.delay-3 {
  animation-delay: 380ms;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.4rem 1.2rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: #0a4a5a;
  font-size: 0.88rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  box-shadow: 0 0 20px rgba(100, 220, 220, 0.15), 0 2px 8px rgba(0, 0, 0, 0.08);
}

.title {
  font-size: clamp(2.2rem, 4vw, 3.6rem);
  font-weight: 800;
  margin: 0;
  background: linear-gradient(135deg, #ffffff 0%, #ffffff 40%, #7ee8e8 70%, #5dd6d6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

// 交叉淡入淡出容器：离开的旧文案绝对定位，避免布局跳动
.subtitle-wrap {
  position: relative;
  width: 100%;
  min-height: calc(1.35em * 1.3);
}

.subtitle {
  font-size: 1rem;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.5;
  margin: 0;
}

.subtitle-switch-enter-active,
.subtitle-switch-leave-active {
  transition:
    opacity 0.55s ease,
    transform 0.55s ease;
}

.subtitle-switch-leave-active {
  position: absolute;
  inset: 0;
}

.subtitle-switch-enter-from {
  opacity: 0;
  transform: translateY(5px);
}

.subtitle-switch-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 1.25rem;
  align-items: center;
  margin-top: 0.6rem;
}

.button-base {
  position: relative;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.5rem 2.2rem;
  border-radius: 999px;
  font-size: 1.05rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  transition:
    background 0.25s ease,
    border-color 0.25s ease,
    box-shadow 0.25s ease;
  min-height: 54px;
  min-width: 11rem;
}

.button-base.primary {
  background: linear-gradient(135deg, var(--main-600), var(--main-500));
  color: var(--gray-0);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 12px 28px -12px rgba(3, 80, 101, 0.55);

  // hover 时一道流光扫过
  &::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: 45%;
    background: linear-gradient(100deg, transparent, rgba(255, 255, 255, 0.32), transparent);
    transform: translateX(-160%) skewX(-18deg);
    transition: transform 0.7s ease;
    pointer-events: none;
  }

  :deep(svg) {
    transition: transform 0.25s ease;
  }

  &:hover {
    background: linear-gradient(135deg, var(--main-700), var(--main-600));
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.22),
      0 16px 34px -12px rgba(3, 80, 101, 0.6);

    &::after {
      transform: translateX(340%) skewX(-18deg);
    }

    :deep(svg) {
      transform: translateX(3px);
    }
  }
}

// 次按钮：玻璃质感，融入流光背景
.button-base.secondary {
  background: var(--color-trans-light);
  backdrop-filter: blur(8px);
  color: var(--main-700);
  border-color: var(--main-40);

  :deep(svg) {
    color: var(--main-600);
  }

  &:hover {
    background: var(--main-30);
    border-color: var(--main-200);
    color: var(--main-800);
  }
}

// 页脚
.footer {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}

.footer-content {
  text-align: center;
  padding: 1rem 2rem;
  max-width: 1180px;
  margin: 0 auto;
}

.copyright {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.82rem;
  font-weight: 400;
  margin: 0;
}

@keyframes bgFlow {
  from {
    background-position: 0% 40%;
  }
  to {
    background-position: 100% 60%;
  }
}

@keyframes glowDrift {
  from {
    transform: translateX(-50%) translate(0, 0) scale(1);
  }
  to {
    transform: translateX(-50%) translate(90px, 60px) scale(1.15);
  }
}

@keyframes glowDriftAccent {
  from {
    transform: translate(0, 0) scale(1);
  }
  to {
    transform: translate(-100px, -70px) scale(1.18);
  }
}

@keyframes revealUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes nodePulse {
  0% {
    opacity: 0.7;
    transform: scale(1);
  }
  70%,
  100% {
    opacity: 0;
    transform: scale(2.4);
  }
}

@keyframes signalFlow {
  to {
    stroke-dashoffset: -146;
  }
}

@keyframes driftA {
  from {
    transform: translate(0, 0);
  }
  to {
    transform: translate(16px, -12px);
  }
}

@keyframes driftB {
  from {
    transform: translate(0, 0);
  }
  to {
    transform: translate(-18px, 10px);
  }
}

@keyframes driftC {
  from {
    transform: translate(0, 0);
  }
  to {
    transform: translate(10px, 14px);
  }
}

// 暗色模式：文字与边框颜色随 token 反转自动适配，只需给次按钮换深色玻璃底
// 注意：:global 包裹嵌套块会被 scoped 编译静默丢弃，必须用 :root.dark 直接嵌套；
// 暗色下 --light-*/--dark-* 名称互换，--dark-10 才是白色 10% 淡色
:root.dark {
  .button-base.secondary {
    background: var(--dark-10);

    &:hover {
      background: var(--dark-25);
    }
  }
}

// 响应式：移动端上下堆叠
@media (max-width: 960px) {
  .hero-section {
    flex-direction: column;
    padding: 5rem 1.5rem 3rem;
    gap: 1.5rem;
  }
  .hero-brand-side {
    width: 100%;
  }
  .hero-content {
    align-items: center;
    text-align: center;
  }
  .hero-login-side {
    flex: none;
    width: 100%;
    max-width: 420px;
  }
  .login-panel {
    width: 100%;
  }
  .hero-vignette {
    left: 50%;
  }
}

@media (max-width: 480px) {
  .login-form-area {
    padding: 28px 20px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .reveal-up {
    opacity: 1;
    transform: none;
    animation: none;
  }

  .ambient::before,
  .drift,
  .pulse-ring,
  .signals .signal,
  .glow,
  .glow-accent {
    animation: none;
  }

  .signals {
    display: none;
  }

  .subtitle-switch-enter-active,
  .subtitle-switch-leave-active {
    transition: none;
  }
}
</style>
