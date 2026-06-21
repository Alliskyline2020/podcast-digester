# Task 7: Frontend Integration - PlayerView Integration

## Overview

This task integrated the subtitle scroll functionality (Task 5) and subtitle mapping component (Task 6) into the PlayerView.vue component, enabling automatic scrolling and visual display of paragraph-to-segment mappings.

## Files Modified

### 1. `/Users/alli/podcast-digester/frontend/src/views/PlayerView.vue`

#### Imports Added
```javascript
import { watch } from 'vue'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'
import SubtitleMapping from '@/components/SubtitleMapping.vue'
```

#### New Refs
- `transcriptContainer`: Ref for the subtitle scroll container
- `isMappingExpanded`: Ref to track expansion state of each mapping

#### Paragraphs Composable Enhanced
Modified the `paragraphs` computed property to prioritize backend `paragraph_mappings`:
```javascript
const paragraphs = computed(() => {
  // Prioritize backend paragraph_mappings if available
  if (bundle.value?.episode?.paragraph_mappings && bundle.value.episode.paragraph_mappings.length > 0) {
    console.log('[PlayerView] Using backend paragraph_mappings')
    return bundle.value.episode.paragraph_mappings
  }

  // Fallback to frontend paragraph generation
  // ... existing logic ...
})
```

#### Scroll Integration
```javascript
// Initialize subtitle scroll functionality
const { scrollToActive } = useSubtitleScroll(transcriptContainer, paragraphs, {
  block: 'center',
  threshold: 500
})

// Watch currentTime changes and scroll to active paragraph
watch(currentTime, (newTime, oldTime) => {
  if (activeTab.value === 'transcript' && newTime !== oldTime) {
    scrollToActive(newTime)
  }
})
```

#### Mapping Toggle Handler
```javascript
const toggleMapping = (paragraphId, expanded) => {
  isMappingExpanded.value[paragraphId] = expanded
}
```

#### Template Changes
1. Added `ref="transcriptContainer"` to transcript content div
2. Added `:data-paragraph-id="idx"` to each paragraph block
3. Integrated `SubtitleMapping` component:
```vue
<SubtitleMapping
  v-if="para.segment_ids && para.segment_indices"
  :paragraph="para"
  :expanded="isMappingExpanded[para.id]"
  @toggle="(expanded) => toggleMapping(para.id, expanded)"
/>
```

### 2. `/Users/alli/podcast-digester/frontend/tests/views/PlayerView.integration.spec.js`

Created comprehensive integration tests covering:

#### Paragraph Mappings Priority
- **Test**: Prioritize backend paragraph_mappings when available
- **Test**: Fallback to frontend paragraph generation when no mappings
- Validates that `paragraph_mappings` from backend are used when present
- Validates fallback to segment-based paragraph generation

#### Subtitle Scroll Integration
- **Test**: Initialize scroll composable with transcript container
- **Test**: Update scroll on currentTime change when transcript tab is active
- Validates `transcriptContainer` ref is initialized
- Validates `scrollToActive` function is available
- Validates scroll behavior on time updates

#### SubtitleMapping Component Integration
- **Test**: Render SubtitleMapping component when paragraph has mapping data
- **Test**: Handle mapping expansion state
- **Test**: Not render mapping when paragraph lacks segment data
- Validates component rendering with correct props
- Validates expansion state management
- Validates conditional rendering based on data availability

#### Paragraph Activation
- **Test**: Correctly identify current paragraph based on time
- Validates `isCurrentParagraph` logic
- Tests paragraph activation at different time points

## Test Results

All tests passing:
```
Test Files  3 passed (3)
Tests       17 passed (17)
```

Breakdown:
- `tests/composables/useSubtitleScroll.test.js`: 6 tests passed
- `tests/components/SubtitleMapping.test.js`: 3 tests passed
- `tests/views/PlayerView.integration.spec.js`: 8 tests passed

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         PlayerView                            │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌───────────────────┐     ┌─────────────────────────────┐   │
│  │ useSubtitleScroll │◄────│   paragraphs computed       │   │
│  └────────┬──────────┘     │   (prioritizes              │   │
│           │                │    paragraph_mappings)      │   │
│           │                └─────────────┬───────────────┘   │
│           │                              │                     │
│           │                              │                     │
│           │                ┌─────────────▼───────────────┐   │
│           │                │   transcriptContainer      │   │
│           │                │   (scroll target)          │   │
│           │                └─────────────┬───────────────┘   │
│           │                              │                     │
│           │                ┌─────────────▼───────────────┐   │
│           │                │   SubtitleMapping          │   │
│           │                │   (per paragraph)          │   │
│           │                └─────────────────────────────┘   │
│           │                                                    │
│           └──────────────► scrollToActive(newTime)            │
│                                                              │
│  watch(currentTime) ────────────────────────────────────────┘
│         │
│         └──► if transcript tab active:
│              scrollToActive(currentTime)
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Backend Data Loading
```
API.fetchEpisode()
  ↓
setBundle(data)
  ↓
bundle.episode.paragraph_mappings (if available)
  ↓
paragraphs computed property
```

### 2. Scroll Behavior
```
audio timeupdate event
  ↓
currentTime ref updated
  ↓
watch(currentTime) triggered
  ↓
scrollToActive(currentTime)
  ↓
findActiveIndex(currentTime)
  ↓
scrollToIndex(activeIndex)
  ↓
element.scrollIntoView()
```

### 3. Mapping Display
```
paragraph.render()
  ↓
if para.segment_ids && para.segment_indices
  ↓
<SubtitleMapping />
  ↓
toggle expansion
  ↓
isMappingExpanded[para.id] updated
```

## Key Features

1. **Automatic Scrolling**: Subtitles automatically scroll to keep current paragraph in view
2. **Backend Priority**: Uses backend `paragraph_mappings` when available for better semantic grouping
3. **Graceful Fallback**: Falls back to frontend paragraph generation when backend data unavailable
4. **Mapping Visualization**: Shows which segments compose each paragraph
5. **Interactive Expansion**: Users can expand mappings to see segment details
6. **Performance Optimized**: Scroll only when tab is active and paragraph changes

## Error Handling

1. **Missing Backend Data**: Falls back to frontend paragraph generation
2. **Empty Data**: Handles empty segments/paragraphs arrays
3. **Invalid Time**: `findActiveIndex` returns -1 for out-of-bounds times
4. **Missing Container**: `scrollToActive` safely returns if container unavailable
5. **Conditional Rendering**: Mapping only shows when `segment_ids` and `segment_indices` present

## Testing Strategy

### Unit Tests (Tasks 5 & 6)
- `useSubtitleScroll`: Scroll logic, binary search, threshold handling
- `SubtitleMapping`: Component rendering, expansion state

### Integration Tests (Task 7)
- Full PlayerView integration
- Data flow from API to display
- Scroll behavior with player time updates
- Mapping component integration
- Paragraph activation logic

## Completion Status

✅ All requirements met:
- ✅ Import useSubtitleScroll composable
- ✅ Import SubtitleMapping component
- ✅ Add transcriptContainer ref
- ✅ Prioritize backend paragraph_mappings
- ✅ Manage mapping expansion state
- ✅ Integrate scroll with player time updates
- ✅ Create comprehensive integration tests
- ✅ All tests passing

## Next Steps

The frontend integration is complete. The system now:
1. Displays semantic paragraphs from backend when available
2. Automatically scrolls to current playing paragraph
3. Shows paragraph-to-segment mappings interactively
4. Handles edge cases gracefully

Ready for end-to-end testing with real podcast data.
