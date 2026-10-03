<template>
  <div
    class="base-loading-state"
    :class="[`base-loading-state--${size}`, { 'base-loading-state--panel': panel }]"
    role="status"
    aria-live="polite"
  >
    <span class="base-loading-state__visual" aria-hidden="true">
      <i class="base-loading-state__ring"></i>
      <i class="base-loading-state__core"></i>
    </span>
    <span class="base-loading-state__copy">
      <strong>{{ text }}</strong>
      <small v-if="description">{{ description }}</small>
    </span>
  </div>
</template>

<script setup>
defineProps({
  text: { type: String, default: '加载中...' },
  description: { type: String, default: '' },
  size: {
    type: String,
    default: 'md',
    validator: value => ['sm', 'md', 'lg'].includes(value),
  },
  panel: { type: Boolean, default: false },
})
</script>

<style scoped>
.base-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 13px;
  color: var(--theme-text-secondary);
}

.base-loading-state--panel {
  min-height: 220px;
  padding: 32px 40px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  background:
    radial-gradient(circle at 30% 0%, rgba(69, 215, 255, 0.06), transparent 60%),
    radial-gradient(circle at 80% 100%, rgba(255, 109, 177, 0.05), transparent 55%),
    rgba(26, 26, 26, 0.72);
  box-shadow:
    0 18px 48px rgba(0, 0, 0, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(14px) saturate(120%);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
}

.base-loading-state__visual {
  position: relative;
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
}

.base-loading-state__ring {
  position: absolute;
  inset: 1px;
  border: 2px solid var(--theme-border-strong);
  border-top-color: #45d7ff;
  border-right-color: #ff6db1;
  border-radius: 50%;
  animation: base-loading-spin .85s linear infinite;
}

.base-loading-state__core {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--theme-text-tertiary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--theme-text-tertiary) 10%, transparent);
}

.base-loading-state__copy { display: grid; gap: 3px; }
.base-loading-state__copy strong { color: var(--theme-text-primary); font-size: 13px; font-weight: 650; }
.base-loading-state__copy small { color: var(--theme-text-muted); font-size: 11px; }
.base-loading-state--sm { gap: 9px; }
.base-loading-state--sm .base-loading-state__visual { width: 22px; height: 22px; flex-basis: 22px; }
.base-loading-state--sm .base-loading-state__ring { border-width: 1.5px; }
.base-loading-state--sm .base-loading-state__core { width: 4px; height: 4px; }
.base-loading-state--sm .base-loading-state__copy strong { font-size: 11px; }
.base-loading-state--lg { flex-direction: column; gap: 14px; text-align: center; }
.base-loading-state--lg .base-loading-state__visual { width: 44px; height: 44px; flex-basis: 44px; }
.base-loading-state--lg .base-loading-state__copy strong { font-size: 14px; }
.base-loading-state--lg .base-loading-state__copy small { font-size: 11px; }

@keyframes base-loading-spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .base-loading-state__ring { animation-duration: 1.8s; }
}
</style>
