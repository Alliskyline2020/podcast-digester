<template>
  <div class="player-pane">
    <audio
      ref="localAudioRef"
      :src="audioUrl"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      controls
      class="audio-player"
    />
  </div>
</template>

<script setup>
import { computed, watch, ref } from 'vue'
import { usePlayer } from '../composables/player'

const { audioRef, onTimeUpdate, onLoadedMetadata, bundle, setAudioRef } = usePlayer()

// 本地ref引用
const localAudioRef = ref(null)

// 监听ref变化，同步到全局状态
watch(localAudioRef, (newRef) => {
  if (newRef) {
    setAudioRef(newRef)
  }
}, { immediate: true })

const audioUrl = computed(() => {
  if (!bundle.value?.episode?.media_path) return ''
  const path = bundle.value.episode.media_path
  // 如果是相对路径，添加 /media 前缀
  if (!path.startsWith('/')) {
    return `/media/${bundle.value.episode.id}/${path.split('/').pop()}`
  }
  return path
})
</script>

<style scoped>
.player-pane {
  width: 100%;
}

.audio-player {
  width: 100%;
  border-radius: 8px;
}
</style>
