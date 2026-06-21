/**
 * useSubtitleScroll 使用示例
 *
 * 这个文件展示了如何在 Vue 3 组件中使用 useSubtitleScroll composable
 */

import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'
import { usePlayer } from '@/composables/player'

export default {
  setup() {
    const containerRef = ref(null)
    const { currentTime, bundle } = usePlayer()

    // 获取字幕段落数据
    const transcriptParagraphs = computed(() => {
      if (!bundle.value?.transcript?.segments) return []
      return bundle.value.transcript.segments
    })

    // 初始化滚动 composable
    const {
      isScrolling,
      scrollToActive,
      scrollToIndex,
      findActiveIndex,
      watchTime
    } = useSubtitleScroll(containerRef, transcriptParagraphs, {
      block: 'center',      // 居中显示当前段落
      threshold: 500        // 500ms 容差
    })

    // 方式 1: 手动监听播放时间变化
    watch(currentTime, (newTime, oldTime) => {
      // 防止滚动时触发循环
      if (isScrolling.value) return

      // 只在切换段落时滚动
      const oldIndex = findActiveIndex(oldTime)
      const newIndex = findActiveIndex(newTime)

      if (oldIndex !== newIndex && newIndex >= 0) {
        scrollToIndex(newIndex)
      }
    })

    // 方式 2: 使用 watchTime 辅助方法（更简洁）
    // watchTime(currentTime)

    // 方式 3: 响应点击跳转
    const handleParagraphClick = (paragraphIndex) => {
      scrollToIndex(paragraphIndex)
    }

    // 方式 4: 响应播放器 seek
    const handlePlayerSeek = (timeMs) => {
      scrollToActive(timeMs)
    }

    return {
      containerRef,
      transcriptParagraphs,
      isScrolling,
      handleParagraphClick,
      handlePlayerSeek
    }
  },

  template: `
    <div>
      <div ref="containerRef" class="subtitle-container">
        <div
          v-for="(paragraph, index) in transcriptParagraphs"
          :key="paragraph.id"
          :data-paragraph-id="index"
          class="subtitle-paragraph"
          :class="{ active: isCurrentParagraph(paragraph, index) }"
          @click="handleParagraphClick(index)"
        >
          {{ paragraph.text }}
        </div>
      </div>
    </div>
  `
}

/**
 * 模板部分示例（在 .vue 文件中）
 */
/*
<template>
  <div class="player-view">
    <!-- 播放器控制 -->
    <audio
      ref="audioRef"
      @timeupdate="onTimeUpdate"
      @seeked="onSeeked"
    />

    <!-- 字幕列表 -->
    <div
      ref="containerRef"
      class="subtitle-container"
      :class="{ scrolling: isScrolling }"
    >
      <div
        v-for="(paragraph, index) in transcriptParagraphs"
        :key="paragraph.id"
        :data-paragraph-id="index"
        class="subtitle-paragraph"
        :class="{ active: isCurrentParagraph(paragraph, index) }"
        @click="handleParagraphClick(index)"
      >
        <div class="paragraph-time">
          {{ formatTime(paragraph.start_ms) }}
        </div>
        <div class="paragraph-text">
          {{ paragraph.text }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'
import { usePlayer } from '@/composables/player'

const containerRef = ref(null)
const { currentTime, bundle, seekTo } = usePlayer()

const transcriptParagraphs = computed(() => {
  if (!bundle.value?.transcript?.segments) return []
  return bundle.value.transcript.segments
})

const {
  isScrolling,
  scrollToActive,
  scrollToIndex,
  findActiveIndex
} = useSubtitleScroll(containerRef, transcriptParagraphs, {
  block: 'center',
  threshold: 500
})

// 自动滚动到当前播放位置
watch(currentTime, (newTime, oldTime) => {
  if (isScrolling.value) return

  const oldIndex = findActiveIndex(oldTime)
  const newIndex = findActiveIndex(newTime)

  if (oldIndex !== newIndex && newIndex >= 0) {
    scrollToIndex(newIndex)
  }
})

// 点击段落跳转播放器
const handleParagraphClick = (index) => {
  const paragraph = transcriptParagraphs.value[index]
  if (paragraph) {
    seekTo(paragraph.start_ms)
  }
}

// 判断是否为当前段落
const isCurrentParagraph = (paragraph, index) => {
  const activeIndex = findActiveIndex(currentTime.value)
  return activeIndex === index
}

// 格式化时间
const formatTime = (ms) => {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}
</script>

<style scoped>
.subtitle-container {
  height: 600px;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.subtitle-container.scrolling {
  pointer-events: none; /* 滚动时禁用点击 */
}

.subtitle-paragraph {
  padding: 12px 16px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.subtitle-paragraph.active {
  background-color: #e3f2fd;
  border-left: 3px solid #2196f3;
}

.subtitle-paragraph:hover {
  background-color: #f5f5f5;
}

.paragraph-time {
  font-size: 0.85em;
  color: #666;
  margin-bottom: 4px;
}

.paragraph-text {
  line-height: 1.6;
}
</style>
*/
