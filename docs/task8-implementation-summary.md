# Task 8: Frontend Optimization - Error Handling and Memory Leak Fixes

## Overview

This task implements critical fixes for memory leaks, race conditions, and error handling in the subtitle scroll feature, as identified in the Task 7 code review.

## Critical Issues Fixed

### 1. Memory Leak: Uncleared Watcher (PlayerView.vue:772-776)
**Problem:** The `watch()` function was called but its return value (stop function) was not stored, preventing cleanup on unmount.

**Solution:**
- Store the watch stop function: `const scrollWatcherStop = watch(...)`
- Call stop function in `onUnmounted`: `scrollWatcherStop()`

### 2. Memory Leak: useSubtitleScroll Timer (useSubtitleScroll.js:95-97)
**Problem:** The scroll timer was never cleared, causing memory leaks.

**Solution:**
- Added `cleanup()` function to the composable
- Clears timer, resets error state, and resets scrolling state
- Exported cleanup function for use in components
- Called in `PlayerView.onUnmounted()`

### 3. Race Condition: Seek Operations (PlayerView.vue:690-725)
**Problem:** Multiple rapid seeks could cause race conditions and unpredictable behavior.

**Solution:**
- Added `isSeeking` flag to track when a seek is in progress
- Added `seekQueue` array to queue pending seeks
- Queue only keeps the most recent seek (replaces entire queue on new seek)
- Process queued seeks in `onAudioSeeked` after current seek completes
- Clear queue on unmount

### 4. Error Handling: Missing User Feedback (PlayerView.vue:727-741)
**Problem:** API errors were only logged to console, users had no feedback.

**Solution:**
- Added `loadError` and `loadErrorMessage` reactive refs
- Added error banner UI with:
  - Error icon and message
  - Retry button to reload episode
  - Dismiss button to hide error
- Errors are now caught and displayed to users

## Files Modified

### `/frontend/src/composables/useSubtitleScroll.js`
**Changes:**
- Added error state refs: `hasError`, `errorMessage`
- Added try-catch blocks to `scrollToIndex` and `scrollToActive`
- Added `cleanup()` function that clears timers and resets state
- Exported `cleanup`, `hasError`, and `errorMessage`

**Key additions:**
```javascript
const hasError = ref(false)
const errorMessage = ref('')

const cleanup = () => {
  if (scrollTimer) {
    clearTimeout(scrollTimer)
    scrollTimer = null
  }
  hasError.value = false
  errorMessage.value = ''
  isScrolling.value = false
}

return {
  isScrolling,
  hasError,
  errorMessage,
  scrollToActive,
  scrollToIndex,
  findActiveIndex,
  watchTime,
  cleanup
}
```

### `/frontend/src/views/PlayerView.vue`
**Changes:**
- Added error state refs: `loadError`, `loadErrorMessage`
- Added seek queue refs: `isSeeking`, `seekQueue`
- Modified `localSeekTo()` to queue seeks when already seeking
- Modified `onAudioSeeked()` to process queue and reset flag
- Modified `loadEpisode()` to catch and store errors
- Added error banner UI to template
- Modified `onUnmounted()` to cleanup scroll composable and watch

**Key additions:**
```javascript
// Error states
const loadError = ref(null)
const loadErrorMessage = ref('')

// Seek queue to prevent race conditions
const isSeeking = ref(false)
const seekQueue = ref([])

// In localSeekTo()
if (isSeeking.value) {
  seekQueue.value.push(ms)
  if (seekQueue.value.length > 1) {
    seekQueue.value = [ms] // Keep only most recent
  }
  return
}

// In onAudioSeeked()
isSeeking.value = false
if (seekQueue.value.length > 0) {
  const nextSeek = seekQueue.value.shift()
  // Process next seek...
}

// In onUnmounted()
if (cleanupScroll) {
  cleanupScroll()
}
if (scrollWatcherStop) {
  scrollWatcherStop()
}
```

## Tests Added

### `/frontend/tests/composables/useSubtitleScroll.test.js`
**New test suites:**
- **Error Handling** (5 tests):
  - Handle missing container gracefully
  - Handle missing target element
  - Handle container becoming null
  - Clear error on successful scroll
  - Handle errors in scrollToActive

- **Memory Leak Prevention** (4 tests):
  - Provide cleanup function
  - Clear timers on cleanup
  - Reset error state on cleanup
  - Handle multiple cleanup calls safely

- **Error State Exposure** (3 tests):
  - Expose hasError ref
  - Expose errorMessage ref
  - Update error state on error

### `/frontend/tests/views/PlayerView.integration.spec.js`
**New test suites:**
- **Error Handling** (4 tests):
  - Handle API errors gracefully
  - Show error banner when load fails
  - Provide retry button on error
  - Dismiss error when dismiss button clicked

- **Seek Race Condition Prevention** (4 tests):
  - Queue seeks when already seeking
  - Replace queue with most recent seek
  - Process queued seek after current completes
  - Reset seeking flag after seek completes

- **Memory Leak Prevention** (3 tests):
  - Cleanup scroll composable on unmount
  - Stop watch on unmount
  - Clear pending seeks on unmount

## Test Results

All 40 tests passing:
- `useSubtitleScroll.test.js`: 19 tests passed
- `PlayerView.integration.spec.js`: 19 tests passed
- `SubtitleMapping.test.js`: 2 tests passed

## Success Criteria Met

✅ **No memory leaks**
- Watchers cleaned up via `scrollWatcherStop()`
- Timers cleared via `cleanupScroll()`
- Seek queues cleared on unmount

✅ **Seek operations safe from race conditions**
- `isSeeking` flag prevents concurrent seeks
- Queue ensures most recent seek is always executed
- Queue processed in order after each seek completes

✅ **Users see helpful error messages**
- Error banner displays API failures
- Retry button allows users to try again
- Dismiss button to hide error
- Errors in scroll operations are caught and logged

✅ **All tests pass including new error tests**
- 40/40 tests passing
- Coverage for error scenarios
- Coverage for memory leak scenarios
- Coverage for seek race conditions

## Performance Impact

- **Minimal overhead:** Error handling adds negligible overhead
- **Improved stability:** Race condition prevention prevents unpredictable behavior
- **Better UX:** Users get feedback on errors instead of silent failures

## Backward Compatibility

All changes are backward compatible:
- Existing functionality unchanged
- New error states are internal to components
- Cleanup functions are called automatically
- Error banner only shows when errors occur

## Next Steps

1. Monitor for any additional memory leaks in production
2. Consider adding error tracking (e.g., Sentry) for production errors
3. Add more granular error types if needed
4. Consider adding user feedback for scroll errors (currently only logged)
