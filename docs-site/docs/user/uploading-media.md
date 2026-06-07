---
id: uploading-media
title: Upload media
sidebar_position: 5
---

# Upload media

Videos and images are stored inside Postgres as large objects — there is no S3
and no external object store. You upload through the media API; the platform
validates the file, ingests the bytes, and gives you back a stable URL.

## Scan box

- **One endpoint.** `POST /api/media/upload` takes a multipart file and returns
  a media URL. Permission `media.upload` (held by `feed_contributor` and
  `content_author`).
- **Strict validation before ingest.** The platform sniffs the MIME type from
  the file header, checks it against size caps, and validates video with
  FFprobe and images with Pillow. A file that fails is rejected, not stored.
- **Stored in Postgres large objects.** Metadata lands in `media_assets`; the
  bytes live as a large object referenced by OID.
- **Served with Range support.** Video streams back from
  `/media/video/{id}` with HTTP Range (seek/scrub works); images from
  `/media/image/{id}`.
- **Size caps are configurable.** `MAX_VIDEO_SIZE_MB` and `MAX_IMAGE_SIZE_MB`
  are set per environment; an oversized upload returns an error.

## Steps — upload a file

```bash
curl -X POST https://internal.in.deptagency.com/api/media/upload \
  --cookie "session=..." \
  -F "file=@/path/to/clip.mp4" \
  -F "surface=feed" \
  -F "title=Branch naming explainer"
```

The response gives you the URL to use:

```jsonc
// video
{ "status": "success", "video_asset_id": "...", "asset_id": "...",
  "url": "/media/video/..." }
// image
{ "status": "success", "asset_id": "...", "url": "/media/image/..." }
```

Use the returned `url` directly — for example as the source of a video feed post
(see [Create feed posts](./creating-feed-posts)).

## What gets checked

| Check | Video | Image |
|---|---|---|
| MIME sniffed from header | ✓ | ✓ |
| Size cap | `MAX_VIDEO_SIZE_MB` | `MAX_IMAGE_SIZE_MB` |
| Deep validation | FFprobe | Pillow |
| Served from | `/media/video/{id}` (Range) | `/media/image/{id}` |

:::caution[Common Pitfall]

The platform trusts the file's **header bytes**, not its extension. Renaming
`notes.txt` to `clip.mp4` will fail validation — the sniffed MIME type won't
match a real video. Upload the genuine file.

:::

:::tip[Why This Matters]

Media in Postgres large objects means one backup covers everything — content,
data and media in a single consistent snapshot — and no second system to secure,
bill or keep in sync. The trade-off is that uploads are validated hard and size
caps matter; the database is not a dumping ground. Keep source masters elsewhere
and upload web-ready renditions.

:::

For the storage internals (large objects, the delete trigger, the `vacuumlo`
sweep), see [media large objects](../developer/data-model/media-large-objects)
in the developer reference.
