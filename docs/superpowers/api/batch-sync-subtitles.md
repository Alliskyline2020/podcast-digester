# Batch Subtitle Sync API

## Overview

The batch subtitle sync API allows administrators to synchronize subtitle segment mappings for multiple existing episodes at once, without needing to re-download audio or re-transcribe content.

## Endpoint

```
POST /api/admin/batch-sync-subtitles
```

## Request Body

```json
{
  "episode_ids": ["ep_001", "ep_002", "ep_003"]
}
```

### Fields

- `episode_ids` (array of strings, required): List of episode IDs to sync

## Response

```json
{
  "total": 3,
  "successful": ["ep_001", "ep_002"],
  "failed": [
    {
      "episode_id": "ep_003",
      "error": "字幕文件不存在"
    }
  ],
  "duration_ms": 123
}
```

### Fields

- `total` (integer): Total number of episodes processed
- `successful` (array of strings): List of successfully synced episode IDs
- `failed` (array of objects): List of failed episodes with error details
  - `episode_id` (string): The episode ID that failed
  - `error` (string): Error message explaining why it failed
- `duration_ms` (integer): Processing time in milliseconds

## Behavior

### Success Case

For each episode ID in the request:

1. Verifies the episode exists in the database
2. Reads the `transcript.json` file from the episode's media directory
3. Processes the subtitle segments using `SubtitleSegmenter.segment()`
4. Persists the resulting paragraph mappings to the database
5. Tracks the episode as successful

### Failure Cases

Individual episode failures don't stop the batch processing:

- **Episode not found**: Episode ID doesn't exist in database
- **Transcript file missing**: No `transcript.json` file in media directory
- **Invalid transcript data**: Empty or malformed transcript data
- **Database errors**: Issues persisting to database

Each failure is tracked with a specific error message in the `failed` array.

### Error Handling

- Empty `episode_ids` array returns HTTP 400
- Individual episode failures return HTTP 200 with details in `failed` array
- Processing continues even if some episodes fail

## Example Usage

### cURL

```bash
curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
  -H "Content-Type: application/json" \
  -d '{
    "episode_ids": ["ep_1718400000000", "ep_1718400001000", "ep_1718400002000"]
  }'
```

### Python

```python
import requests

response = requests.post(
    "http://localhost:8000/api/admin/batch-sync-subtitles",
    json={
        "episode_ids": ["ep_001", "ep_002", "ep_003"]
    }
)

data = response.json()
print(f"Processed {data['total']} episodes")
print(f"Successful: {len(data['successful'])}")
print(f"Failed: {len(data['failed'])}")

if data['failed']:
    for failure in data['failed']:
        print(f"  {failure['episode_id']}: {failure['error']}")
```

### JavaScript

```javascript
const response = await fetch('http://localhost:8000/api/admin/batch-sync-subtitles', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    episode_ids: ['ep_001', 'ep_002', 'ep_003']
  })
});

const data = await response.json();
console.log(`Processed ${data.total} episodes`);
console.log(`Successful: ${data.successful.length}`);
console.log(`Failed: ${data.failed.length}`);

if (data.failed.length > 0) {
  data.failed.forEach(failure => {
    console.log(`  ${failure.episode_id}: ${failure.error}`);
  });
}
```

## Performance

- Typical processing: ~1ms per episode
- 10 episodes: <10ms
- 100 episodes: <100ms

Performance depends on:
- Number of segments per episode
- Disk I/O speed
- Database write performance

## Use Cases

1. **Bulk Migration**: Sync all existing episodes after deploying the subtitle mapping feature
2. **Periodic Re-sync**: Update paragraph mappings after modifying segmentation rules
3. **Fix Failed Syncs**: Retry sync for episodes that previously failed
4. **Batch Processing**: Process multiple episodes in one operation instead of individual API calls

## Related APIs

- `POST /api/episodes/{episode_id}/sync-subtitles` - Sync single episode
- `GET /api/episode/{episode_id}` - Get episode details including paragraph mappings

## Error Messages

Common error messages in the `failed` array:

- `"节目不存在"` - Episode not found in database
- `"字幕文件不存在"` - Transcript file missing
- `"字幕数据为空或格式错误"` - Invalid or empty transcript data
- Other database or processing errors
