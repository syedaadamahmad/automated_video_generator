// // src/lib/api.ts
// // All calls go through Next.js /api/proxy/* which forwards to veo_main.py.
// // Auth headers are added by the proxy layer from the NextAuth session.

// const BASE = '/api/proxy'

// async function req<T>(path: string, init?: RequestInit): Promise<T> {
//   const res = await fetch(`${BASE}${path}`, {
//     headers: { 'Content-Type': 'application/json', ...init?.headers },
//     ...init,
//   })
//   if (!res.ok) {
//     const err = await res.text().catch(() => res.statusText)
//     throw new Error(`API ${res.status}: ${err}`)
//   }
//   return res.json()
// }

// // ── Health ─────────────────────────────────────────────────────────────────
// export const checkHealth = () =>
//   fetch(`${BASE}/health`).then(r => r.ok).catch(() => false)

// // ── Upload ─────────────────────────────────────────────────────────────────
// export async function uploadFile(file: File) {
//   const form = new FormData()
//   form.append('file', file)
//   const res = await fetch(`${BASE}/api/upload`, { method: 'POST', body: form })
//   if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
//   return res.json()
// }

// // ── Jobs ───────────────────────────────────────────────────────────────────
// export const listJobs   = ()          => req<{ jobs: any[] }>('/api/jobs').then(r => r.jobs)
// export const fetchJob   = (id: string) => req<any>(`/api/jobs/${id}`)
// export const rerunPrompt = (jobId: string, idx: number) =>
//   req<any>(`/api/jobs/${jobId}/rerun/${idx}`, { method: 'POST' })
// export const approveVideo = (jobId: string, idx: number) =>
//   req<any>(`/api/jobs/${jobId}/approve/${idx}`, { method: 'POST' })

// // ── Metrics ────────────────────────────────────────────────────────────────
// export const fetchMetrics = () => req<any>('/api/metrics')

// // ── YouTube ────────────────────────────────────────────────────────────────
// export const fetchYouTubeStatus = () => req<any>('/api/youtube/status')
// export const fetchYouTubeQueue  = () => req<{ queue: any[] }>('/api/youtube/queue').then(r => r.queue)
// export const updateQueueItem = (id: string, body: { title: string; description: string; tags: string[] }) =>
//   req<any>(`/api/youtube/queue/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
// export const removeFromQueue = (id: string) =>
//   req<any>(`/api/youtube/queue/${id}`, { method: 'DELETE' })
// export const triggerYouTubeUpload = () =>
//   req<any>('/api/youtube/upload', { method: 'POST' })

// // ── Local video URL helper ──────────────────────────────────────────────────
// // The <video> player always uses the local FastAPI route, never S3 directly
// // (S3 needs CORS headers to stream in-browser).
// export function localVideoSrc(localUrl: string | null, s3Url?: string | null): string | null {
//   if (!localUrl) return null
//   if (localUrl.startsWith('http')) {
//     // S3 URL was stored as local_video_url — extract filename and serve via proxy
//     const filename = localUrl.split('/').pop()
//     return filename ? `/api/proxy/videos/${filename}` : null
//   }
//   // /videos/filename.mp4 — prepend proxy prefix
//   return `/api/proxy${localUrl}`
// }





















// // src/lib/api.ts
// // All calls go through Next.js /api/proxy/* which forwards to veo_main.py.
// // Auth headers are added by the proxy layer from the NextAuth session.

// import type {
//   Job,
//   JobListItem,
//   Metrics,
//   YouTubeQueueItem,
//   YouTubeStatus,
//   YouTubeUploadResult,
//   UploadResult,
//   ApproveResult,
//   RerunResult,
// } from '@/types'

// const BASE = '/api/proxy'

// async function req<T>(path: string, init?: RequestInit): Promise<T> {
//   const res = await fetch(`${BASE}${path}`, {
//     headers: { 'Content-Type': 'application/json', ...init?.headers },
//     ...init,
//   })
//   if (!res.ok) {
//     const err = await res.text().catch(() => res.statusText)
//     throw new Error(`API ${res.status}: ${err}`)
//   }
//   return res.json() as Promise<T>
// }

// // ── Health ─────────────────────────────────────────────────────────────────
// export const checkHealth = (): Promise<boolean> =>
//   fetch(`${BASE}/health`).then(r => r.ok).catch(() => false)

// // ── Upload ─────────────────────────────────────────────────────────────────
// export interface UploadOptions {
//   mode:         'full' | 'short_span' | 'short_span_image'
//   clipDuration: number   // short_span video: seconds per clip (2–8)
//   holdDuration: number   // short_span_image: seconds per image (2 or 5)
//   noText:       boolean
//   noSpeech:     boolean
// }

// export async function uploadFile(file: File, opts: UploadOptions): Promise<UploadResult> {
//   const form = new FormData()
//   form.append('file', file)
//   const params = new URLSearchParams({
//     mode:          opts.mode,
//     clip_duration: String(opts.clipDuration),
//     hold_duration: String(opts.holdDuration),
//     no_text:       String(opts.noText),
//     no_speech:     String(opts.noSpeech),
//   })
//   const res = await fetch(`${BASE}/api/upload?${params}`, {
//     method: 'POST',
//     body:   form,
//   })
//   if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
//   return res.json() as Promise<UploadResult>
// }

// // ── Jobs ───────────────────────────────────────────────────────────────────
// export const listJobs = (): Promise<JobListItem[]> =>
//   req<{ jobs: JobListItem[] }>('/api/jobs').then(r => r.jobs)

// export const fetchJob = (id: string): Promise<Job> =>
//   req<Job>(`/api/jobs/${id}`)

// export const rerunPrompt = (jobId: string, idx: number): Promise<RerunResult> =>
//   req<RerunResult>(`/api/jobs/${jobId}/rerun/${idx}`, { method: 'POST' })

// export const approveVideo = (jobId: string, idx: number): Promise<ApproveResult> =>
//   req<ApproveResult>(`/api/jobs/${jobId}/approve/${idx}`, { method: 'POST' })

// // ── Metrics ────────────────────────────────────────────────────────────────
// export const fetchMetrics = (): Promise<Metrics> =>
//   req<Metrics>('/api/metrics')

// // ── YouTube ────────────────────────────────────────────────────────────────
// export const fetchYouTubeStatus = (): Promise<YouTubeStatus> =>
//   req<YouTubeStatus>('/api/youtube/status')

// export const fetchYouTubeQueue = (): Promise<YouTubeQueueItem[]> =>
//   req<{ queue: YouTubeQueueItem[] }>('/api/youtube/queue').then(r => r.queue)

// export const updateQueueItem = (
//   id: string,
//   body: { title: string; description: string; tags: string[] },
// ): Promise<{ success: boolean }> =>
//   req<{ success: boolean }>(`/api/youtube/queue/${id}`, {
//     method: 'PATCH',
//     body:   JSON.stringify(body),
//   })

// export const removeFromQueue = (id: string): Promise<{ success: boolean }> =>
//   req<{ success: boolean }>(`/api/youtube/queue/${id}`, { method: 'DELETE' })

// export const triggerYouTubeUpload = (): Promise<YouTubeUploadResult> =>
//   req<YouTubeUploadResult>('/api/youtube/upload', { method: 'POST' })

// // ── Local video URL helper ──────────────────────────────────────────────────
// // Always serve video via local FastAPI proxy — S3 URLs need CORS headers.
// export function localVideoSrc(
//   localUrl: string | null,
//   _s3Url?: string | null,
// ): string | null {
//   if (!localUrl) return null
//   if (localUrl.startsWith('http')) {
//     // S3 URL stored as local_video_url — extract filename, serve via proxy
//     const filename = localUrl.split('/').pop()
//     return filename ? `/api/proxy/videos/${filename}` : null
//   }
//   return `/api/proxy${localUrl}`
// }
















// src/lib/api.ts
// All calls go through Next.js /api/proxy/* which forwards to veo_main.py.
// Auth headers are added by the proxy layer from the NextAuth session.

import type {
  Job,
  JobListItem,
  Metrics,
  YouTubeQueueItem,
  YouTubeStatus,
  YouTubeUploadResult,
  UploadResult,
  ApproveResult,
  RerunResult,
} from '@/types'

const BASE = '/api/proxy'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${err}`)
  }
  return res.json() as Promise<T>
}

// ── Health ─────────────────────────────────────────────────────────────────
export const checkHealth = (): Promise<boolean> =>
  fetch(`${BASE}/health`).then(r => r.ok).catch(() => false)

// ── Upload ─────────────────────────────────────────────────────────────────
export interface UploadOptions {
  mode:         'full' | 'short_span' | 'short_span_image'
  clipDuration: number   // short_span video: seconds per clip (2–8)
  holdDuration: number   // short_span_image: seconds per image (2 or 5)
  noText:       boolean
  noSpeech:     boolean
}

export async function uploadFile(file: File, opts: UploadOptions): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const params = new URLSearchParams({
    mode:          opts.mode,
    clip_duration: String(opts.clipDuration),
    hold_duration: String(opts.holdDuration),
    no_text:       String(opts.noText),
    no_speech:     String(opts.noSpeech),
  })
  const res = await fetch(`${BASE}/api/upload?${params}`, {
    method: 'POST',
    body:   form,
  })
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
  return res.json() as Promise<UploadResult>
}

// ── Jobs ───────────────────────────────────────────────────────────────────
export const listJobs = (): Promise<JobListItem[]> =>
  req<{ jobs: JobListItem[] }>('/api/jobs').then(r => r.jobs)

export const fetchJob = (id: string): Promise<Job> =>
  req<Job>(`/api/jobs/${id}`)

export const rerunPrompt = (jobId: string, idx: number): Promise<RerunResult> =>
  req<RerunResult>(`/api/jobs/${jobId}/rerun/${idx}`, { method: 'POST' })

export const approveVideo = (jobId: string, idx: number): Promise<ApproveResult> =>
  req<ApproveResult>(`/api/jobs/${jobId}/approve/${idx}`, { method: 'POST' })

// ── Metrics ────────────────────────────────────────────────────────────────
export const fetchMetrics = (): Promise<Metrics> =>
  req<Metrics>('/api/metrics')

// ── YouTube ────────────────────────────────────────────────────────────────
export const fetchYouTubeStatus = (): Promise<YouTubeStatus> =>
  req<YouTubeStatus>('/api/youtube/status')

export const fetchYouTubeQueue = (): Promise<YouTubeQueueItem[]> =>
  req<{ queue: YouTubeQueueItem[] }>('/api/youtube/queue').then(r => r.queue)

export const updateQueueItem = (
  id: string,
  body: { title: string; description: string; tags: string[] },
): Promise<{ success: boolean }> =>
  req<{ success: boolean }>(`/api/youtube/queue/${id}`, {
    method: 'PATCH',
    body:   JSON.stringify(body),
  })

export const removeFromQueue = (id: string): Promise<{ success: boolean }> =>
  req<{ success: boolean }>(`/api/youtube/queue/${id}`, { method: 'DELETE' })

export const triggerYouTubeUpload = (): Promise<YouTubeUploadResult> =>
  req<YouTubeUploadResult>('/api/youtube/upload', { method: 'POST' })

// ── Local video URL helper ──────────────────────────────────────────────────
// Always serve video via local FastAPI proxy — S3 URLs need CORS headers.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function localVideoSrc(
  localUrl: string | null,
  _s3Url?: string | null,
): string | null {
  if (!localUrl) return null
  if (localUrl.startsWith('http')) {
    // S3 URL stored as local_video_url — extract filename, serve via proxy
    const filename = localUrl.split('/').pop()
    return filename ? `/api/proxy/videos/${filename}` : null
  }
  return `/api/proxy${localUrl}`
}

// ── Refinement API ─────────────────────────────────────────────────────────────
import type { RefineResponse, RefinedRow } from '@/types'

export async function refinePrompts(
  file: File,
  opts: UploadOptions & { refinerMode?: 1 | 2 },
): Promise<RefineResponse> {
  const form   = new FormData()
  form.append('file', file)
  const params = new URLSearchParams({
    mode:          opts.mode,
    clip_duration: String(opts.clipDuration),
    hold_duration: String(opts.holdDuration),
    no_text:       String(opts.noText),
    no_speech:     String(opts.noSpeech),
    ...(opts.refinerMode ? { refiner_mode_override: String(opts.refinerMode) } : {}),
  })
  const res = await fetch(`${BASE}/api/refine?${params}`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Refinement failed: ${res.statusText}`)
  const data = await res.json()
  // Normalise snake_case → camelCase for frontend
  return {
    jobId:       data.job_id,
    totalRows:   data.total_rows,
    mode:        data.mode,
    refinerMode: data.refiner_mode,
    rows:        (data.rows ?? []).map(normaliseRefinedRow),
  }
}

export async function approveJob(
  jobId: string,
  approvedRows: { rowIndex: number; finalPrompt: string }[],
): Promise<{ success: boolean; jobId: string }> {
  const res = await fetch(`${BASE}/api/jobs/${jobId}/approve`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      approved_rows: approvedRows.map(r => ({
        row_index:    r.rowIndex,
        final_prompt: r.finalPrompt,
      })),
    }),
  })
  if (!res.ok) throw new Error(`Approve failed: ${res.statusText}`)
  const d = await res.json()
  return { success: d.success, jobId: d.job_id }
}

export async function rejectJob(jobId: string): Promise<void> {
  await fetch(`${BASE}/api/jobs/${jobId}/reject`, { method: 'POST' })
}

export async function refineRowAgain(
  jobId: string,
  rowIndex: number,
): Promise<RefinedRow> {
  const res = await fetch(`${BASE}/api/jobs/${jobId}/refine-row/${rowIndex}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`Refine row failed: ${res.statusText}`)
  const d = await res.json()
  return normaliseRefinedRow(d.row)
}

function normaliseRefinedRow(r: Record<string, unknown>): RefinedRow {
  const s = (r.structured ?? {}) as Record<string, unknown>
  return {
    rowIndex:          Number(r.row_index ?? 0),
    rowNumber:         Number(r.row_number ?? 1),
    originalPrompt:    String(r.original_prompt ?? ''),
    refinedPrompt:     String(r.refined_prompt ?? ''),
    mythologyDetected: Boolean(r.mythology_detected),
    warnings:          (r.warnings as string[]) ?? [],
    structured: {
      scene:          String(s.scene ?? ''),
      characters:     String(s.characters ?? ''),
      camera:         String(s.camera ?? ''),
      narrationLines: (s.narration_lines as string[]) ?? [],
      lighting:       String(s.lighting ?? ''),
      mythologyNotes: String(s.mythology_notes ?? ''),
    },
    clips:      normaliseClips(r.clips as Record<string, unknown>[] ?? []),
    nClips:     Number(r.n_clips ?? 1),
    duration:   Number(r.duration ?? 8),
    clipsReady: Boolean(r.clips_ready),
  }
}

function normaliseClips(clips: Record<string, unknown>[]): import('@/types').ClipTimestamp[] {
  return clips.map(c => ({
    clip:      Number(c.clip ?? 1),
    durationS: Number(c.duration_s ?? 8),
    startS:    Number(c.start_s ?? 0),
    endS:      Number(c.end_s ?? 8),
    endState:  String(c.end_state ?? ''),
    prompt:    String(c.prompt ?? ''),
    label:     String(c.label ?? ''),
  }))
}