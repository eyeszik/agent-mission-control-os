# n8n adapter

A thin wrapper that lets an existing n8n instance drive FreeVideoForge. It is
**not** required: n8n is one optional consumer of the local API, never a
dependency of the pipeline.

`fvf_node.py` is a plain stdin/stdout JSON bridge, which is the shape n8n's
**Execute Command** node expects. No n8n SDK, no npm package, no service.

## Wire it up

Add an *Execute Command* node:

```
Command:   python3
Arguments: /path/to/services/freevideoforge/integrations/n8n/fvf_node.py
```

Send the request on stdin:

```json
{
  "action": "generate",
  "workspace": "/srv/video-jobs",
  "request": {
    "topic": "Why the moon changes shape",
    "duration": 30,
    "aspect": "9:16",
    "quality_preset": "balanced",
    "seed": 42
  }
}
```

You get back:

```json
{
  "ok": true,
  "run_id": "run-20260915-010203-a1b2c3",
  "state": "COMPLETED",
  "final_video": "/srv/video-jobs/out/run-.../final.mp4",
  "thumbnail": "...", "captions": "...", "manifest": "...",
  "duration": 30.4,
  "providers": {"render": "ffmpeg_motion", "speech": "espeak"},
  "warnings": []
}
```

## Actions

| `action` | Fields | Returns |
| --- | --- | --- |
| `generate` | `request` | the finished run |
| `resume` | `run_id` | the resumed run |
| `status` | `run_id` | state, per-scene progress, recent events |
| `runs` | `limit` | recent runs |
| `doctor` | — | host capability report |

`workspace` is accepted on every action.

## Notes

- Exit code is `0` on success and `1` on failure; `ok` in the payload says the
  same thing, so either is safe to branch on.
- Long renders block the node. For a fire-and-forget queue, call `generate` in
  a background worker and poll `status`, which is cheap.
- Nothing here needs a credential. If your n8n instance has none configured for
  this node, that is correct.
