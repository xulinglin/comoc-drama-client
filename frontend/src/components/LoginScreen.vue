<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['submit'])
const isRegister = ref(false)
const username = ref('')
const password = ref('')
const remember = ref(true)
const agreementAccepted = ref(true)
const showPassword = ref(false)
const localError = ref('')
const visibleError = computed(() => localError.value || props.error)

onMounted(async () => {
  try {
    const saved = await window.pywebview?.api?.get_saved_credentials?.()
    if (!saved?.remember) return
    username.value = saved.username || ''
    password.value = saved.password || ''
    remember.value = true
  } catch {
    // 凭据读取失败时保持空表单，不阻断登录。
  }
})

function switchMode(register) {
  isRegister.value = register
  localError.value = ''
}

function submit() {
  localError.value = ''
  if (!username.value.trim()) {
    localError.value = '请输入用户名'
    return
  }
  if (password.value.length < 6) {
    localError.value = '密码长度不能少于 6 位'
    return
  }
  if (!agreementAccepted.value) {
    localError.value = '请先阅读并同意用户协议和隐私政策'
    return
  }
  emit('submit', {
    mode: isRegister.value ? 'register' : 'login',
    username: username.value.trim(),
    password: password.value,
    remember: remember.value,
  })
}
</script>

<template>
  <section class="cdtv-auth-screen" aria-labelledby="auth-title">
    <div class="cdtv-auth-dialog">
      <div class="cdtv-brand-panel">
        <div class="cdtv-brand-glow cdtv-brand-glow-one"></div>
        <div class="cdtv-brand-glow cdtv-brand-glow-two"></div>
        <div class="cdtv-brand-grid"></div>

        <div class="cdtv-brand-logo" aria-label="CDTV ComicDrama TV">
          <div class="cdtv-brand-main"><span>CD</span><strong>TV</strong></div>
          <div class="cdtv-brand-sub">COMICDRAMA TV</div>
        </div>

        <div class="cdtv-brand-copy">
          <span class="cdtv-brand-badge"><i></i>AI 漫剧创作平台</span>
          <h1>让每一个故事<br />都成为精彩画面</h1>
          <p>从剧本、角色、场景到分镜与成片，<br />在 CDTV 完成你的智能创作流程。</p>
        </div>

        <div class="cdtv-visual-card cdtv-visual-card-back"></div>
        <div class="cdtv-visual-card cdtv-visual-card-middle"></div>
        <div class="cdtv-visual-card cdtv-visual-card-front">
          <div class="cdtv-play-icon">
            <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M18 13.5v21l18-10.5-18-10.5Z" /></svg>
          </div>
          <div class="cdtv-visual-lines"><span></span><span></span><span></span></div>
        </div>
      </div>

      <div class="cdtv-form-panel">
        <div class="cdtv-form-wrap">
          <div class="cdtv-tabs" role="tablist" aria-label="账号操作">
            <button type="button" role="tab" :aria-selected="!isRegister" :class="{ active: !isRegister }" @click="switchMode(false)">登录</button>
            <button type="button" role="tab" :aria-selected="isRegister" :class="{ active: isRegister }" @click="switchMode(true)">注册</button>
            <span class="cdtv-tab-indicator" :class="{ register: isRegister }"></span>
          </div>

          <div class="cdtv-form-heading">
            <h2 id="auth-title">{{ isRegister ? '创建你的 CDTV 账号' : '欢迎回来' }}</h2>
            <p>{{ isRegister ? '注册后即可开启 AI 漫剧创作' : '登录后继续管理你的作品与资产' }}</p>
          </div>

          <form @submit.prevent="submit">
            <label class="cdtv-field" for="auth-username">
              <span>用户名</span>
              <div class="cdtv-input-shell">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm7 8a7 7 0 0 0-14 0" /></svg>
                <input id="auth-username" v-model="username" autocomplete="username" maxlength="64" placeholder="请输入用户名" autofocus @input="localError = ''" />
              </div>
            </label>

            <label class="cdtv-field" for="auth-password">
              <span>密码</span>
              <div class="cdtv-input-shell">
                <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
                <input id="auth-password" v-model="password" :type="showPassword ? 'text' : 'password'" :autocomplete="isRegister ? 'new-password' : 'current-password'" placeholder="请输入密码" @input="localError = ''" />
                <button class="cdtv-password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
                  <svg v-if="!showPassword" viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" /><circle cx="12" cy="12" r="2.6" /></svg>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 18 18M10.6 6.2A10.8 10.8 0 0 1 12 6c6 0 9.5 6 9.5 6a14.8 14.8 0 0 1-2.1 2.8M6.5 6.5C4 8.2 2.5 12 2.5 12s3.5 6 9.5 6a9.8 9.8 0 0 0 3-.5" /></svg>
                </button>
              </div>
            </label>

            <div class="cdtv-form-options">
              <label class="cdtv-remember">
                <input v-model="remember" type="checkbox" />
                <span></span>{{ isRegister ? '注册后保持登录' : '记住我' }}
              </label>
              <small>登录凭证仅保存在本机</small>
            </div>

            <p v-if="visibleError" class="cdtv-auth-error" role="alert" aria-live="assertive">{{ visibleError }}</p>

            <button class="cdtv-submit-btn" type="submit" :disabled="loading">
              <span v-if="loading" class="cdtv-loading-dot"></span>
              {{ loading ? '处理中...' : isRegister ? '立即注册' : '立即登录' }}
              <svg v-if="!loading" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
            </button>
          </form>

          <label class="cdtv-agreement">
            <input v-model="agreementAccepted" type="checkbox" />
            <span><svg v-if="agreementAccepted" viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7" /></svg></span>
            我已阅读并同意用户协议和隐私政策
          </label>
        </div>
      </div>
    </div>
  </section>
</template>
