<template>
  <Teleport to="body">
    <Transition name="track-dialog-fade">
      <div v-if="visible" class="track-dialog-overlay" @mousedown.self="close">
        <section ref="dialogRef" class="track-dialog" role="dialog" aria-modal="true" aria-labelledby="project-track-title" tabindex="-1" @mousedown.stop>
          <header class="track-dialog-head">
            <div class="track-dialog-heading">
              <span>FINAL CUT PREVIEW</span>
              <h2 id="project-track-title">项目成片</h2>
              <p>{{ projectTitle || '未命名项目' }}</p>
            </div>
            <div class="track-dialog-summary"><b>{{ videos.length }}</b> 个视频片段</div>
            <button class="track-close" type="button" aria-label="关闭成片预览" @click="close">
              <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </header>

          <div v-if="loading" class="track-loading-wrap">
            <BaseLoadingState size="lg" text="正在加载项目成片…" description="读取视频片段并整理 V1 轨道" />
          </div>
          <div v-else-if="error" class="track-dialog-state error"><strong>成片加载失败</strong><span>{{ error }}</span></div>
          <div v-else-if="!videos.length" class="track-dialog-state"><strong>当前项目还没有成片</strong><span>完成视频生成后，再从项目列表点击“成片”。</span></div>

          <div v-else class="track-editor">
            <aside class="track-assets">
              <header><strong>成片列表</strong><span>{{ videos.length }}</span></header>
              <div class="track-asset-list">
                <button v-for="(item, index) in videos" :key="`asset-${item.id}`" type="button" class="track-asset-item" :class="{ active: activeVideoId === item.id, hidden: isVideoHidden(item) }" @click="selectVideo(item.id, 0)">
                  <span class="track-asset-thumb">
                    <video :src="item.src" muted preload="auto" @loadeddata="ensureVideoRenderable(item, $event)" @error="safeEmitVideoError(item)"></video>
                    <i>{{ String(index + 1).padStart(2, '0') }}</i>
                  </span>
                  <span class="track-asset-info">
                    <strong>{{ item.title }}</strong>
                    <span class="track-asset-meta">
                      <small>{{ formatTime(mediaDuration(item)) }} · 视频</small>
                      <span class="track-asset-toggle" :class="{ off: isVideoHidden(item) }" role="button" tabindex="0" :aria-label="isVideoHidden(item) ? '在轨道显示' : '从轨道隐藏'" :data-tooltip="isVideoHidden(item) ? '在轨道显示' : '从轨道隐藏'" @click.stop="toggleVideoHidden(item)" @keydown.stop.enter.prevent="toggleVideoHidden(item)" @keydown.stop.space.prevent="toggleVideoHidden(item)">
                        <svg v-if="!isVideoHidden(item)" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 18 18M10.6 10.6a3 3 0 0 0 4 4M9.4 5.2A9.5 9.5 0 0 1 12 5c6.5 0 10 7 10 7a17.8 17.8 0 0 1-3.3 4.1M6.1 6.1A17.8 17.8 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 3.8-1"/></svg>
                      </span>
                    </span>
                  </span>
                </button>
              </div>
            </aside>

            <section class="track-player">
              <header class="track-player-head">
                <div><i></i><strong>预览监视器</strong></div>
                <span>{{ activeVideo?.title || '没有可播放的成片' }}</span>
                <label class="track-pack-prefix" data-tooltip="可选。填 1 时导出为 101、102；留空导出为 01、02">
                  <span>序号前缀</span>
                  <input
                    :value="sequencePrefix"
                    type="text"
                    inputmode="numeric"
                    maxlength="8"
                    placeholder="不添加"
                    aria-label="打包视频序号前缀，可不填写"
                    :disabled="packaging"
                    @input="updateSequencePrefix"
                  />
                </label>
                <button
                  type="button"
                  class="track-pack-btn"
                  :disabled="packaging || !videos.length"
                  :data-tooltip="packMessage || '按分镜顺序打包所有成片到视频输出目录'"
                  @click="packageVideos"
                >
                  <svg v-if="!packaging" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 7v10l10 4 10-4V7L12 3Zm0 0v18M2 7l10 4 10-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>
                  <span v-else class="track-pack-spin" aria-hidden="true"></span>
                  <span>{{ packaging ? '打包中…' : '打包成片' }}</span>
                </button>
              </header>
              <div class="track-monitor">
                <div class="track-player-stage">
                  <video v-for="clip in videoTimeline" :key="clip.id" :ref="el => setPlayerVideo(el, clip)" :class="['player-video', { active: activeVideoId === clip.id }]" :src="clip.src" playsinline preload="auto" @click="togglePlayback" @loadedmetadata="onMainVideoMetadata($event, clip)" @loadeddata="ensureVideoRenderable(clip, $event)" @durationchange="onMainVideoMetadata($event, clip)" @timeupdate="onMainVideoTime" @play="onVideoPlay" @pause="onVideoPause" @volumechange="onVolumeChange" @ended="advanceVideo" @error="safeEmitVideoError(clip)"></video>
                </div>
                <footer class="track-player-controls">
                  <button type="button" :aria-label="playing ? '暂停' : '播放'" @click="togglePlayback">
                    <svg v-if="playing" viewBox="0 0 24 24"><path d="M7.5 5.5h3.5v13H7.5zM13 5.5h3.5v13H13z" /></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="m9 6.7 9 5.3-9 5.3z" /></svg>
                  </button>
                  <div class="track-progress-control">
                    <input type="range" min="0" :max="totalDuration" step="0.01" :value="currentTime" :style="{ '--track-progress': `${timelineProgress * 100}%` }" aria-label="项目视频播放进度" @input="seekTimeline(Number($event.target.value))" />
                    <div><span class="track-time current">{{ formatTime(currentTime) }}</span><span class="track-time">{{ formatTime(totalDuration) }}</span></div>
                  </div>
                  <button type="button" :aria-label="muted ? '打开声音' : '静音'" @click="toggleMuted">
                    <svg v-if="muted" viewBox="0 0 24 24"><path d="M4 10v4h4l5 4V6l-5 4H4zM17 9l4 6M21 9l-4 6" /></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="M4 10v4h4l5 4V6l-5 4H4zM16 9c1.5 1.4 1.5 4.6 0 6M19 7c3 2.7 3 7.3 0 10" /></svg>
                  </button>
                </footer>
              </div>
            </section>

            <section class="project-timeline" aria-label="项目视频轨道">
              <header><div><strong>视频轨道</strong><span>PROJECT TIMELINE</span></div><p>V1 · {{ videos.length }} 个片段 · {{ Math.round(timelineZoom * 100) }}%</p></header>
              <div ref="timelineScrollRef" class="timeline-scroll" @wheel="zoomTimeline">
                <div class="timeline-content" :style="{ width: `${timelineZoom * 100}%` }">
                  <div class="timeline-ruler"><span v-for="mark in rulerMarks" :key="mark" :style="{ left: `${mark / timelineDuration * 100}%` }">{{ formatTime(mark) }}</span></div>
                  <div class="timeline-row">
                    <span class="timeline-label">V1</span>
                    <div ref="timelineLaneRef" class="timeline-lane">
                      <button v-for="clip in videoTimeline" :key="clip.id" type="button" class="timeline-clip" :class="{ active: activeVideoId === clip.id }" :style="clipStyle(clip)" @click="selectVideo(clip.id, clip.duration * pointerRatio($event))">
                        <span class="clip-filmstrip"><video v-for="frame in filmstripFrameCount(clip)" :key="`${clip.id}-${frame}`" :src="clip.src" muted playsinline preload="auto" @loadedmetadata="loadFilmstripFrame($event, frame, filmstripFrameCount(clip))" @loadeddata="ensureVideoRenderable(clip, $event)" @error="safeEmitVideoError(clip)"></video></span>
                        <strong>{{ clip.title }}</strong>
                      </button>
                      <button class="timeline-playhead" :class="{ dragging: draggingPlayhead }" type="button" :style="{ left: `${timelinePosition * 100}%` }" aria-label="拖动播放指针" @pointerdown.stop.prevent="startPlayheadDrag"></button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import BaseLoadingState from './BaseLoadingState.vue'
import { watchForDecodedVideoFrame } from '../utils/videoCompatibility.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  projectTitle: { type: String, default: '' },
  videos: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  token: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'video-error'])
const dialogRef = ref(null)
const videoRef = ref(null)
const timelineScrollRef = ref(null)
const timelineLaneRef = ref(null)
// 视频元素池：每个片段一个 <video preload="auto">，切换片段只切可见性，避免重建造成的卡顿
const playerVideos = new Map()       // clipId -> HTMLVideoElement
function setPlayerVideo(el, clip) {
  if (el) {
    playerVideos.set(clip.id, el)
    if (clip.id === activeVideoId.value) videoRef.value = el
  } else {
    playerVideos.delete(clip.id)
  }
}
const activeVideoId = ref('')
const currentTime = ref(0)
const playing = ref(false)
const draggingPlayhead = ref(false)
const timelineZoom = ref(1)
const muted = ref(false)
const measuredDurations = reactive({})
const hiddenVideoIds = ref(new Set())
function isVideoHidden(video) { return video ? hiddenVideoIds.value.has(String(video.id)) : false }
function toggleVideoHidden(video) {
  if (!video?.id) return
  const id = String(video.id)
  const next = new Set(hiddenVideoIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  hiddenVideoIds.value = next
}
let previousFocus = null
let previousBodyOverflow = ''
let playbackFrame = 0
let playbackVideo = null
let playbackTick = null
let scrubFrame = 0
let pendingScrubX = 0
let scrubWasPlaying = false
let videoSelectionVersion = 0
let stopVideoFrameWatch = null
let isUnmounted = false
// 安全 emit：组件卸载后或实例被回收时，emit 内部访问 instance.emitsOptions 可能拿到 null 抛错
function safeEmitVideoError(clip) {
  if (isUnmounted) return
  try { emit('video-error', clip) } catch (_) {}
}

function ensureVideoRenderable(clip, event) {
  const video = event.currentTarget
  window.setTimeout(() => {
    if (!video.isConnected || isUnmounted) return
    if (video.videoWidth <= 0 || video.videoHeight <= 0) safeEmitVideoError(clip)
  }, 250)
}

function mediaDuration(item) { return Math.max(.1, Number(measuredDurations[item.id] || item.duration) || 5) }
function buildTimeline(items) { let start = 0; return items.map(item => { const duration = mediaDuration(item); const clip = { ...item, start, duration }; start += duration; return clip }) }
const videoTimeline = computed(() => buildTimeline(props.videos.filter(v => !isVideoHidden(v))))
const totalDuration = computed(() => videoTimeline.value.at(-1)?.start + videoTimeline.value.at(-1)?.duration || 0)
const timelineDuration = computed(() => Math.max(5, Math.ceil(totalDuration.value)))
const timelineProgress = computed(() => totalDuration.value ? Math.min(1, currentTime.value / totalDuration.value) : 0)
const timelinePosition = computed(() => Math.min(1, currentTime.value / timelineDuration.value))
const activeVideo = computed(() => props.videos.find(item => item.id === activeVideoId.value) || props.videos[0])
const rulerMarks = computed(() => { const step = timelineDuration.value <= 12 ? 2 : timelineDuration.value <= 30 ? 5 : 10; const marks = []; for (let n = 0; n <= timelineDuration.value; n += step) marks.push(n); if (marks.at(-1) !== timelineDuration.value) marks.push(timelineDuration.value); return marks })

watch(() => props.visible, async visible => {
  if (visible) {
    sequencePrefix.value = ''
    previousFocus = document.activeElement
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeydown)
    await nextTick()
    dialogRef.value?.focus()
  } else cleanup()
})
watch(() => props.videos, videos => {
  if (!videos.some(item => item.id === activeVideoId.value)) activeVideoId.value = videos[0]?.id || ''
  currentTime.value = 0
  playing.value = false
  hiddenVideoIds.value = new Set()
}, { deep: true, immediate: true })
watch(activeVideoId, id => { videoRef.value = playerVideos.get(id) || null })
onBeforeUnmount(() => { isUnmounted = true; cleanup() })

function close() { emit('update:visible', false) }

// 视频打包：按分镜顺序下载到 <outputDir>/<项目名>/01.mp4、02.mp4、...
const packaging = ref(false)
const packMessage = ref('')
const sequencePrefix = ref('')
function safePackName(name) {
  return String(name || '未命名项目').replace(/[\\/:*?"<>|\r\n\t]+/g, '_').replace(/^\.+|\.+$/g, '').trim() || '未命名项目'
}
function updateSequencePrefix(event) {
  const value = String(event?.target?.value || '').replace(/\D/g, '').slice(0, 8)
  sequencePrefix.value = value
  if (event?.target && event.target.value !== value) event.target.value = value
}
async function packageVideos() {
  if (packaging.value || !props.videos.length) return
  if (!window.pywebview?.api?.package_project_videos) {
    packMessage.value = '当前客户端不支持打包功能'
    return
  }
  packaging.value = true
  packMessage.value = '正在准备打包目录…'
  try {
    const payload = props.videos.map((item, index) => ({
      fileId: String(item.fileId || ''),
      title: String(item.title || `成片 ${index + 1}`),
      sequencePrefix: sequencePrefix.value,
    }))
    const result = await window.pywebview.api.package_project_videos(
      props.projectTitle,
      payload,
      props.token,
    )
    const saved = Array.isArray(result?.saved) ? result.saved.length : 0
    const skipped = Array.isArray(result?.skipped) ? result.skipped.length : 0
    if (skipped > 0) {
      packMessage.value = `已打包 ${saved} 个，跳过 ${skipped} 个失败项；目录：${result.projectDir}`
    } else {
      packMessage.value = `已打包 ${saved} 个成片到：${result.projectDir}`
    }
    // 打包成功后在系统资源管理器中打开目录
    if (result?.projectDir && window.pywebview?.api?.open_path) {
      window.pywebview.api.open_path(result.projectDir).catch(() => {})
    }
  } catch (err) {
    packMessage.value = String(err?.message || err || '打包失败')
  } finally {
    packaging.value = false
  }
}
function cleanup() { for (const v of playerVideos.values()) v.pause(); stopVideoFrameWatch?.(); stopVideoFrameWatch = null; stopPlaybackClock(); stopPlayheadDrag(false); playing.value = false; window.removeEventListener('keydown', onKeydown); document.body.style.overflow = previousBodyOverflow; previousFocus?.focus?.(); previousFocus = null }
function onKeydown(event) { if (event.key === 'Escape') close(); if (event.key === ' ' && !['INPUT', 'BUTTON'].includes(event.target?.tagName)) { event.preventDefault(); togglePlayback() } }
function onMainVideoMetadata(event, clip) { if (!clip) return; const value = Number(event.currentTarget.duration); if (Number.isFinite(value) && value > 0) measuredDurations[clip.id] = value }
function currentVideoClip() { return videoTimeline.value.find(clip => clip.id === activeVideo.value?.id) }
function updatePlaybackTime(video, mediaTime = video?.currentTime) {
  if (!video || video !== videoRef.value || draggingPlayhead.value) return
  const clip = currentVideoClip()
  if (!clip) return
  currentTime.value = Math.min(totalDuration.value, clip.start + (Number(mediaTime) || 0))
  keepPlayheadVisible()
}
function onMainVideoTime(event) { updatePlaybackTime(event.currentTarget) }
function startPlaybackClock() {
  stopPlaybackClock()
  const video = videoRef.value
  if (!video) return
  playbackVideo = video
  playbackTick = (_, metadata) => {
    if (!playing.value || video !== videoRef.value) return
    updatePlaybackTime(video, metadata?.mediaTime)
    playbackFrame = typeof video.requestVideoFrameCallback === 'function'
      ? video.requestVideoFrameCallback(playbackTick)
      : requestAnimationFrame(playbackTick)
  }
  playbackFrame = typeof video.requestVideoFrameCallback === 'function'
    ? video.requestVideoFrameCallback(playbackTick)
    : requestAnimationFrame(playbackTick)
}
function stopPlaybackClock() {
  if (playbackFrame && playbackVideo) {
    if (typeof playbackVideo.cancelVideoFrameCallback === 'function') playbackVideo.cancelVideoFrameCallback(playbackFrame)
    else cancelAnimationFrame(playbackFrame)
  }
  playbackFrame = 0
  playbackVideo = null
  playbackTick = null
}
function onVideoPlay(event) { if (event.currentTarget !== videoRef.value) return; playing.value = true; startPlaybackClock(); stopVideoFrameWatch?.(); stopVideoFrameWatch = watchForDecodedVideoFrame(event.currentTarget, () => safeEmitVideoError(activeVideo.value)) }
function onVideoPause(event) { if (event.currentTarget !== videoRef.value) return; playing.value = false; stopVideoFrameWatch?.(); stopVideoFrameWatch = null; stopPlaybackClock() }
function onVolumeChange(event) { if (event.currentTarget !== videoRef.value) return; muted.value = event.currentTarget.muted }
function togglePlayback() { const video = videoRef.value; if (!video) return; if (video.paused) video.play().catch(() => {}); else video.pause() }
function toggleMuted() { const video = videoRef.value; if (!video) return; video.muted = !video.muted; muted.value = video.muted }
function setVideoTimeWhenReady(video, offset, version, resume) {
  const apply = () => {
    if (version !== videoSelectionVersion || video !== videoRef.value) return
    const duration = Number(video.duration)
    video.currentTime = Math.max(0, Math.min(Number.isFinite(duration) ? duration : offset, offset))
    video.muted = muted.value
    updatePlaybackTime(video, video.currentTime)
    if (resume) video.play().catch(() => {})
  }
  if (video.readyState >= 1) apply()
  else video.addEventListener('loadedmetadata', apply, { once: true })
}
function selectVideo(id, offset = 0, forceResume) {
  const clip = videoTimeline.value.find(item => item.id === id)
  if (!clip) return
  const resume = forceResume ?? playing.value
  const version = ++videoSelectionVersion
  videoRef.value?.pause()
  activeVideoId.value = id
  currentTime.value = clip.start + Math.max(0, Math.min(clip.duration, offset))
  nextTick(() => {
    const video = videoRef.value
    if (!video || version !== videoSelectionVersion) return
    setVideoTimeWhenReady(video, offset, version, resume)
  })
}
function seekTimeline(time) {
  const safe = Math.max(0, Math.min(totalDuration.value, Number(time) || 0))
  const clip = videoTimeline.value.find(item => safe >= item.start && safe < item.start + item.duration) || videoTimeline.value.at(-1)
  if (!clip) return
  const offset = Math.max(0, safe - clip.start)
  currentTime.value = safe
  if (clip.id !== activeVideoId.value) selectVideo(clip.id, offset)
  else if (videoRef.value && Number.isFinite(videoRef.value.duration)) videoRef.value.currentTime = Math.min(videoRef.value.duration, offset)
}
function scrubTimelineAt(clientX) {
  const rect = timelineLaneRef.value?.getBoundingClientRect()
  if (!rect?.width) return
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  seekTimeline(ratio * timelineDuration.value)
}
function flushPlayheadDrag() { scrubFrame = 0; scrubTimelineAt(pendingScrubX) }
function movePlayheadDrag(event) {
  if (!draggingPlayhead.value) return
  pendingScrubX = event.clientX
  if (!scrubFrame) scrubFrame = requestAnimationFrame(flushPlayheadDrag)
}
function startPlayheadDrag(event) {
  draggingPlayhead.value = true
  scrubWasPlaying = playing.value
  videoRef.value?.pause()
  pendingScrubX = event.clientX
  scrubTimelineAt(event.clientX)
  window.addEventListener('pointermove', movePlayheadDrag)
  window.addEventListener('pointerup', stopPlayheadDrag, { once: true })
  window.addEventListener('pointercancel', stopPlayheadDrag, { once: true })
}
function stopPlayheadDrag(resumePlayback = true) {
  if (!draggingPlayhead.value) return
  draggingPlayhead.value = false
  cancelAnimationFrame(scrubFrame)
  scrubFrame = 0
  window.removeEventListener('pointermove', movePlayheadDrag)
  window.removeEventListener('pointerup', stopPlayheadDrag)
  window.removeEventListener('pointercancel', stopPlayheadDrag)
  if (scrubWasPlaying && resumePlayback !== false) nextTick(() => videoRef.value?.play().catch(() => {}))
  scrubWasPlaying = false
}
function advanceVideo() { const index = videoTimeline.value.findIndex(item => item.id === activeVideo.value?.id); const next = videoTimeline.value[index + 1]; if (next) selectVideo(next.id, 0, true); else { playing.value = false; stopPlaybackClock() } }
function keepPlayheadVisible() {
  if (timelineZoom.value <= 1 || draggingPlayhead.value) return
  const scroller = timelineScrollRef.value
  const lane = timelineLaneRef.value
  if (!scroller || !lane) return
  const scrollerRect = scroller.getBoundingClientRect()
  const laneRect = lane.getBoundingClientRect()
  const x = laneRect.left - scrollerRect.left + laneRect.width * timelinePosition.value
  const margin = 72
  if (x > scroller.clientWidth - margin) scroller.scrollLeft += x - scroller.clientWidth + margin
  else if (x < margin + 56) scroller.scrollLeft -= margin + 56 - x
}
function zoomTimeline(event) {
  const scroller = timelineScrollRef.value
  if (!scroller) return
  event.preventDefault()
  const oldZoom = timelineZoom.value
  const delta = event.deltaY || event.deltaX
  const nextZoom = Math.max(1, Math.min(8, oldZoom * Math.exp(-delta * .0018)))
  if (Math.abs(nextZoom - oldZoom) < .001) return
  const rect = scroller.getBoundingClientRect()
  const cursorX = Math.max(0, Math.min(scroller.clientWidth, event.clientX - rect.left))
  const anchor = (scroller.scrollLeft + cursorX) / Math.max(1, scroller.scrollWidth)
  timelineZoom.value = nextZoom
  nextTick(() => { scroller.scrollLeft = anchor * scroller.scrollWidth - cursorX })
}
function pointerRatio(event) { const rect = event.currentTarget.getBoundingClientRect(); return Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) }
function clipStyle(clip) { return { left: `${clip.start / timelineDuration.value * 100}%`, width: `${Math.max(3, clip.duration / timelineDuration.value * 100)}%` } }
// 胶片帧数：片段越宽/占比越大帧越多，2-6 帧足够看出内容；多了浪费 video 元素
function filmstripFrameCount(clip) {
  const base = clip.duration / Math.max(.1, totalDuration.value) * 12 * Math.sqrt(timelineZoom.value)
  return Math.max(2, Math.min(6, Math.ceil(base)))
}
// 每个 <video> 在 metadata 加载后 seek 到自己负责的时间点，浏览器原生显示该帧
function loadFilmstripFrame(event, index, count) {
  const video = event.currentTarget
  const duration = Number(video.duration)
  if (Number.isFinite(duration) && duration > 0) {
    video.currentTime = Math.max(0, Math.min(duration - 0.04, duration * ((index - 0.5) / count)))
  }
}
function formatTime(value) { const seconds = Math.max(0, Math.floor(Number(value) || 0)); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` }
</script>

<style scoped>
.track-dialog-overlay{position:fixed;z-index:16000;inset:0;display:grid;place-items:center;box-sizing:border-box;padding:12px 28px;background:#050608e8;backdrop-filter:blur(14px)}
.track-dialog{display:grid;width:min(1240px,calc(100vw - 56px));height:min(940px,calc(100vh - 24px));min-height:590px;grid-template-rows:72px minmax(0,1fr);overflow:hidden;border:1px solid #393d43;border-radius:18px;outline:0;color:#edf1f4;background:#151719;box-shadow:0 40px 120px #000e}
.track-dialog-head{display:grid;grid-template-columns:minmax(0,1fr) auto 38px;align-items:center;gap:20px;padding:0 18px 0 24px;border-bottom:1px solid #2a2d31;background:linear-gradient(180deg,#202326,#1b1d20)}
.track-dialog-heading{display:grid;grid-template-columns:auto auto;align-items:baseline;justify-content:start;gap:4px 12px;min-width:0}.track-dialog-heading>span{color:#76cce1;font:700 9px/1 Consolas,monospace;letter-spacing:.16em}.track-dialog-heading h2{margin:0;color:#f6f8fa;font-size:17px}.track-dialog-heading p{grid-column:1/-1;overflow:hidden;margin:0;color:#747a81;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.track-dialog-summary{padding:7px 11px;border:1px solid #343a40;border-radius:99px;color:#818891;background:#15181b;font-size:10px}.track-dialog-summary b{color:#d8e2e7;font-size:11px}.track-close{display:grid;width:36px;height:36px;place-items:center;padding:0;border:1px solid #373c42;border-radius:9px;color:#a7adb4;background:#272b2f;cursor:pointer;transition:.16s}.track-close:hover{border-color:#50575f;color:#fff;background:#34393f}.track-close svg{width:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}
.track-loading-wrap{display:grid;place-items:center;padding:40px}.track-dialog-state{display:grid;place-content:center;justify-items:center;gap:9px;color:#737980;text-align:center}.track-dialog-state strong{color:#c9ced3;font-size:14px}.track-dialog-state span{max-width:500px;font-size:12px;line-height:1.6}.track-dialog-state.error strong{color:#e4a1aa}.track-dialog-state.error span{color:#a7747b}
.track-editor{display:grid;min-height:0;grid-template-columns:264px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 210px}.track-assets{display:grid;min-height:0;grid-template-rows:48px minmax(0,1fr);border-right:1px solid #2b2e32;background:#17191b}.track-assets>header{display:flex;height:48px;box-sizing:border-box;align-items:center;justify-content:space-between;padding:0 15px;border-bottom:1px solid #2b2e32}.track-assets header strong{color:#eef1f3;font-size:13px}.track-assets header span{display:grid;min-width:24px;height:24px;place-items:center;border-radius:6px;color:#c5c9cd;background:#292d31;font:11px/1 Consolas,monospace}.track-asset-list{padding:10px;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;scrollbar-color:#3a3f45 transparent}.track-asset-list::-webkit-scrollbar{width:8px;height:8px}.track-asset-list::-webkit-scrollbar-track{margin:4px 0;background:transparent}.track-asset-list::-webkit-scrollbar-thumb{border:2px solid transparent;border-radius:99px;background-color:#3a3f45;background-clip:padding-box;transition:background-color .15s}.track-asset-list::-webkit-scrollbar-thumb:hover{background-color:#555b62}.track-asset-item{display:grid;width:100%;grid-template-columns:88px minmax(0,1fr);align-items:center;gap:11px;margin-bottom:6px;padding:8px;border:1px solid transparent;border-radius:9px;background:transparent;text-align:left;cursor:pointer;transition:.15s}.track-asset-item:hover{border-color:#3a3e43;background:#222529}.track-asset-item.active{border-color:#777;background:#2b2e32;box-shadow:inset 3px 0 #f2f2f2}.track-asset-item.hidden{opacity:.5}.track-asset-thumb{position:relative;display:grid;width:88px;height:52px;overflow:hidden;place-items:center;border:1px solid #30343a;border-radius:6px;background:#08090b}.track-asset-thumb video{width:100%;height:100%;object-fit:cover;pointer-events:none}.track-asset-thumb i{position:absolute;right:4px;bottom:4px;padding:3px 5px;border-radius:3px;color:#fff;background:#050607d9;font:700 9px/1 Consolas,monospace;font-style:normal}.track-asset-info{display:flex;flex-direction:column;gap:7px;min-width:0}.track-asset-meta{display:flex;align-items:center;gap:6px;min-width:0}.track-asset-list strong,.track-asset-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track-asset-list strong{color:#f2f3f4;font-size:12px;line-height:1.25}.track-asset-list small{color:#a0a6ac;font-size:10px;flex:1 1 auto;min-width:0}.track-asset-toggle{flex:0 0 auto;display:grid;width:20px;height:20px;place-items:center;padding:0;border:1px solid #34373d;border-radius:5px;color:#9aa0a6;background:#1b1e22;cursor:pointer;transition:.15s}.track-asset-toggle:hover{border-color:#5a5f66;color:#f0f2f4;background:#262a2f}.track-asset-toggle.off{color:#555;border-color:#2a2d33}.track-asset-toggle svg{width:12px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.track-player{display:grid;min-height:0;grid-template-rows:48px minmax(0,1fr);background:#101214}.track-player-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 16px;border-bottom:1px solid #282c30;background:#17191b}.track-player-head>div{display:flex;align-items:center;gap:8px}.track-player-head i{width:7px;height:7px;border-radius:50%;background:#d6d8da;box-shadow:0 0 9px #ffffff55}.track-player-head strong{color:#e4e7e9;font-size:12px}.track-player-head>span{flex:1 1 auto;overflow:hidden;color:#959ba1;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.track-pack-btn{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 13px;border:1px solid #3a3f45;border-radius:8px;color:#e4e7e9;background:#22262b;cursor:pointer;font-size:12px;transition:border-color .15s ease,color .15s ease,background .15s ease}.track-pack-btn:hover:not(:disabled){border-color:#777;background:#2c3137}.track-pack-btn:disabled{cursor:not-allowed;opacity:.55}.track-pack-btn svg{width:14px;height:14px;flex:0 0 auto}.track-pack-spin{width:13px;height:13px;flex:0 0 auto;border:2px solid #ffffff33;border-top-color:#fff;border-radius:50%;animation:track-pack-spin .8s linear infinite}@keyframes track-pack-spin{to{transform:rotate(360deg)}}.track-monitor{position:relative;display:grid;min-height:0;margin:14px 18px 16px;overflow:hidden;border:1px solid #30353a;border-radius:12px;background:#08090b;box-shadow:0 18px 45px #0008}.track-player-stage{position:relative;display:grid;min-height:0;place-items:center;overflow:hidden;background:radial-gradient(circle at 50% 35%,#252a30,#08090b 70%)}.track-player-stage>video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#050607;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .12s}.track-player-stage>video.active{opacity:1;pointer-events:auto}
.track-pack-prefix{flex:0 0 auto;display:flex;height:30px;box-sizing:border-box;align-items:center;gap:7px;padding:0 5px 0 9px;border:1px solid #343940;border-radius:8px;color:#858c93;background:#121518;font-size:10px}.track-pack-prefix input{width:66px;height:22px;box-sizing:border-box;padding:0 7px;border:1px solid #353a40;border-radius:5px;outline:0;color:#eef1f3;background:#202429;font:11px/1 Consolas,monospace}.track-pack-prefix input::placeholder{color:#646b72}.track-pack-prefix input:focus{border-color:#76818a;box-shadow:0 0 0 2px #76818a25}.track-pack-prefix input:disabled{opacity:.55}
.track-player-controls{position:absolute;z-index:3;bottom:12px;left:50%;display:grid;box-sizing:border-box;width:min(640px,calc(100% - 28px));height:56px;grid-template-columns:40px minmax(120px,1fr) 40px;align-items:center;gap:13px;padding:0 13px;border:1px solid #ffffff24;border-radius:11px;background:rgba(13,15,17,.68);box-shadow:0 10px 30px #0008;opacity:0;pointer-events:none;transform:translate(-50%,8px);transition:opacity .18s ease,transform .18s ease;backdrop-filter:blur(12px) saturate(120%);-webkit-backdrop-filter:blur(12px) saturate(120%)}.track-monitor:hover .track-player-controls,.track-player-controls:focus-within{opacity:1;pointer-events:auto;transform:translate(-50%,0)}.track-player-controls>button{display:grid;width:38px;height:38px;place-items:center;padding:0;border:1px solid #ffffff24;border-radius:9px;color:#eceff1;background:#ffffff12;cursor:pointer;transition:.15s}.track-player-controls>button:hover,.track-player-controls>button:focus-visible{border-color:#ffffff80;outline:0;color:#fff;background:#ffffff24}.track-player-controls button svg{width:18px;fill:currentColor;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}.track-progress-control{display:grid;min-width:0;gap:7px}.track-progress-control>div{display:flex;align-items:center;justify-content:space-between}.track-time{color:#b1b6bb;font:10px/1 Consolas,monospace}.track-time.current{color:#fff}.track-progress-control input{width:100%;height:6px;margin:0;appearance:none;border-radius:99px;background:linear-gradient(90deg,#f0f0f0 var(--track-progress),#ffffff3b var(--track-progress));cursor:pointer}.track-progress-control input::-webkit-slider-thumb{width:15px;height:15px;appearance:none;border:3px solid #15181b;border-radius:50%;background:#fff;box-shadow:0 0 0 1px #ffffff80}.track-progress-control input:focus-visible{outline:2px solid #ffffff75;outline-offset:4px}@media(hover:none){.track-player-controls{opacity:1;pointer-events:auto;transform:translate(-50%,0)}}
.project-timeline{grid-column:1/-1;display:grid;min-height:0;grid-template-rows:42px minmax(0,1fr);border-top:1px solid #30343a;background:#181a1c}.project-timeline>header{display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #2b2f33}.project-timeline>header>div{display:flex;align-items:center;gap:8px}.project-timeline header strong{font-size:11px}.project-timeline header span{color:#5f666d;font:8px/1 Consolas,monospace;letter-spacing:.12em}.project-timeline header p{margin:0;color:#747b82;font-size:9px}.timeline-scroll{min-width:0;overflow:auto}.timeline-ruler{position:relative;height:30px;margin-left:56px;border-bottom:1px solid #2c3035;background:repeating-linear-gradient(90deg,transparent 0,transparent calc(10% - 1px),#ffffff0b calc(10% - 1px),#ffffff0b 10%)}.timeline-ruler span{position:absolute;top:11px;color:#646b72;font:8px/1 Consolas,monospace;transform:translateX(-50%)}.timeline-row{display:grid;height:108px;grid-template-columns:56px minmax(0,1fr)}.timeline-label{position:relative;display:grid;place-items:center;border-right:1px solid #30343a;color:#a0a7ad;font:700 10px/1 Consolas,monospace}.timeline-label::before{position:absolute;top:10px;bottom:10px;left:0;width:2px;background:#70c8de;content:""}.timeline-lane{position:relative;margin:8px 12px 8px 0;background:#ffffff05}.timeline-clip{position:absolute;top:5px;bottom:5px;display:flex;min-width:52px;align-items:flex-end;overflow:hidden;padding:0;border:1px solid #66b6c94d;border-radius:5px;color:#fff;background:#1f4f5b;cursor:pointer}.timeline-clip:hover{border-color:#79c9dc}.timeline-clip.active{border-color:#bcecf5;box-shadow:0 0 0 1px #8ed3e66b,0 7px 22px #0006}.timeline-clip>strong{position:relative;z-index:2;display:block;width:100%;overflow:hidden;padding:5px 7px;background:linear-gradient(180deg,transparent,#06090bd9);font-size:8px;text-align:left;text-overflow:ellipsis;white-space:nowrap}.clip-filmstrip{position:absolute;inset:0;display:flex;opacity:.82;pointer-events:none}.clip-filmstrip video{flex:1 0 0;min-width:0;height:100%;object-fit:cover}.timeline-playhead{position:absolute;z-index:5;top:-30px;bottom:0;width:1px;background:#f16c7b;pointer-events:none}.timeline-playhead::before{position:absolute;top:0;left:-4px;width:9px;height:7px;background:#f16c7b;clip-path:polygon(0 0,100% 0,50% 100%);content:""}
.timeline-scroll{overflow-x:auto;overflow-y:hidden}.timeline-content{height:100%;min-width:100%}.timeline-content .timeline-ruler{box-sizing:border-box;width:calc(100% - 56px)}.timeline-content .timeline-row{width:100%}.timeline-content .clip-filmstrip video{flex:1 0 0;min-width:0}
.timeline-playhead{width:17px;padding:0;border:0;outline:0;color:#fff;background:transparent;cursor:ew-resize;pointer-events:auto;transform:translateX(-50%);touch-action:none}.timeline-playhead::after{position:absolute;top:0;bottom:0;left:8px;width:1px;background:#fff;box-shadow:0 0 6px #000b;content:""}.timeline-playhead::before{z-index:1;left:4px;background:#fff}.timeline-playhead:focus-visible::after{left:7.5px;width:2px}.timeline-playhead.dragging{cursor:grabbing}
.track-dialog-fade-enter-active,.track-dialog-fade-leave-active{transition:opacity .18s}.track-dialog-fade-enter-from,.track-dialog-fade-leave-to{opacity:0}@media(max-width:850px),(max-height:650px){.track-dialog-overlay{padding:10px}.track-dialog{width:calc(100vw - 20px);height:calc(100vh - 20px);min-height:0}.track-editor{grid-template-columns:210px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 170px}.track-monitor{margin:8px 10px 10px}.track-player-controls{bottom:8px;width:calc(100% - 20px)}.project-timeline{grid-template-rows:36px minmax(0,1fr)}.timeline-row{height:94px}}
.track-editor{grid-template-rows:minmax(0,1fr) 180px}.timeline-row{height:90px}.track-player-stage>video{object-fit:cover}
@media(max-width:850px),(max-height:650px){.track-editor{grid-template-rows:minmax(0,1fr) 170px}.timeline-row{height:78px}}
</style>
