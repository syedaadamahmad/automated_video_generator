// // src/types/index.ts

// export type Role = 'admin' | 'editor' | 'viewer'

// export interface User {
//   name:  string
//   email: string
//   role:  Role
// }

// export type JobStatus    = 'pending' | 'processing' | 'completed' | 'partial' | 'failed'
// export type PromptStatus = 'pending' | 'processing' | 'completed' | 'partial' | 'failed'
// export type TaskType     = 'AUTO' | 'TEXT_VIDEO' | 'MULTI_SHOT_AUTOMATED'
// export type GenerationMode = 'full' | 'short_span' | 'short_span_image'

// export interface Prompt {
//   prompt_id:                string
//   prompt_text:              string
//   row_number:               number
//   duration:                 number
//   status:                   PromptStatus
//   video_url:                string | null
//   local_video_url:          string | null
//   duration_seconds:         number | null
//   stitched:                 boolean
//   clips_count:              number
//   clip_urls:                string[]
//   model_used:               string
//   has_native_audio:         boolean
//   error_message:            string | null
//   generation_time_seconds:  number | null
//   aspect_ratio?:            string
// }

// export interface Job {
//   job_id:             string
//   original_filename:  string
//   status:             JobStatus
//   total_prompts:      number
//   completed_prompts:  number
//   failed_prompts:     number
//   progress_percent:   number
//   created_at:         string
//   generation_status:  string
//   user_id?:           string
//   prompts:            Prompt[]
//   elapsed_seconds?:   number
//   // Mode and generation options (returned by get_job)
//   mode?:              GenerationMode
//   clip_duration?:     number
//   hold_duration?:     number
//   no_text?:           boolean
//   no_speech?:         boolean
// }

// export interface JobListItem {
//   job_id:             string
//   original_filename:  string
//   status:             JobStatus
//   total_prompts:      number
//   completed_prompts:  number
//   failed_prompts:     number
//   progress_percent:   number
//   created_at:         string
//   generation_status:  string
//   user_id?:           string
// }

// export interface Metrics {
//   jobs_processed: number
//   veo: {
//     submissions:       number
//     successes:         number
//     failures:          number
//     clips_generated:   number
//     avg_clip_time_s:   number
//     total_gen_time_s:  number
//     rate_limit_hits:   number
//     rate_limit_pct:    number
//   }
//   decomposer: {
//     nova_calls:     number
//     deepseek_calls: number
//     deterministic:  number
//     input_tokens:   number
//     output_tokens:  number
//   }
//   s3: {
//     uploads_ok:   number
//     uploads_fail: number
//   }
//   cost_estimate: {
//     usd:  number
//     inr:  number
//     note: string
//   }
// }

// export interface YouTubeStatus {
//   configured:    boolean
//   authenticated: boolean
// }

// export interface YouTubeUploadResult {
//   status:   string
//   uploaded: number
//   message?: string
// }

// export interface YouTubeQueueItem {
//   id:            string
//   queue_id?:     string   // optional — some responses use id only
//   job_id:        string
//   prompt_index:  number
//   prompt_text:   string
//   local_path:    string | null
//   s3_url:        string | null
//   video_url:     string | null
//   title:         string
//   description:   string
//   tags:          string[]
//   status:        string
//   youtube_url:   string | null
//   error:         string | null
// }

// export interface UploadResult {
//   success:       boolean
//   job_id:        string
//   upload_id:     string
//   total_prompts: number
// }

// export interface ApproveResult {
//   success:   boolean
//   queue_id?: string   // present when video is queued for YouTube
//   message?:  string
// }

// export interface RerunResult {
//   success:  boolean
//   message?: string
// }

// // Excel preview row (client-side only)
// export interface PreviewRow {
//   prompt:       string
//   duration:     number
//   aspect_ratio?: string
//   task_type?:   string
//   priority?:    number
// }



























// src/types/index.ts

export type Role    = 'admin' | 'editor' | 'viewer'
export type AppRole = Role   // alias used in next-auth.d.ts and auth-options.ts

export interface User {
  name:  string
  email: string
  role:  Role
}

export type JobStatus    = 'pending' | 'processing' | 'completed' | 'partial' | 'failed'
export type PromptStatus = 'pending' | 'processing' | 'completed' | 'partial' | 'failed'
export type TaskType     = 'AUTO' | 'TEXT_VIDEO' | 'MULTI_SHOT_AUTOMATED'
export type GenerationMode = 'full' | 'short_span' | 'short_span_image'

export interface Prompt {
  prompt_id:                string
  prompt_text:              string
  row_number:               number
  duration:                 number
  status:                   PromptStatus
  video_url:                string | null
  local_video_url:          string | null
  duration_seconds:         number | null
  stitched:                 boolean
  clips_count:              number
  clip_urls:                string[]
  model_used:               string
  has_native_audio:         boolean
  error_message:            string | null
  generation_time_seconds:  number | null
  aspect_ratio?:            string
}

export interface Job {
  job_id:             string
  original_filename:  string
  status:             JobStatus
  total_prompts:      number
  completed_prompts:  number
  failed_prompts:     number
  progress_percent:   number
  created_at:         string
  generation_status:  string
  user_id?:           string
  prompts:            Prompt[]
  elapsed_seconds?:   number
  // Mode and generation options (returned by get_job)
  mode?:              GenerationMode
  clip_duration?:     number
  hold_duration?:     number
  no_text?:           boolean
  no_speech?:         boolean
}

export interface JobListItem {
  job_id:             string
  original_filename:  string
  status:             JobStatus
  total_prompts:      number
  completed_prompts:  number
  failed_prompts:     number
  progress_percent:   number
  created_at:         string
  generation_status:  string
  user_id?:           string
}

export interface Metrics {
  jobs_processed: number
  veo: {
    submissions:       number
    successes:         number
    failures:          number
    clips_generated:   number
    avg_clip_time_s:   number
    total_gen_time_s:  number
    rate_limit_hits:   number
    rate_limit_pct:    number
  }
  decomposer: {
    nova_calls:     number
    deepseek_calls: number
    deterministic:  number
    input_tokens:   number
    output_tokens:  number
  }
  s3: {
    uploads_ok:   number
    uploads_fail: number
  }
  cost_estimate: {
    usd:  number
    inr:  number
    note: string
  }
}

export interface YouTubeStatus {
  configured:    boolean
  authenticated: boolean
}

export interface YouTubeUploadResult {
  status:   string
  uploaded: number
  message?: string
}

export interface YouTubeQueueItem {
  id:            string
  queue_id?:     string   // optional — some responses use id only
  job_id:        string
  prompt_index:  number
  prompt_text:   string
  local_path:    string | null
  s3_url:        string | null
  video_url:     string | null
  title:         string
  description:   string
  tags:          string[]
  status:        string
  youtube_url:   string | null
  error:         string | null
}

export interface UploadResult {
  success:       boolean
  job_id:        string
  upload_id:     string
  total_prompts: number
}

export interface ApproveResult {
  success:   boolean
  queue_id?: string   // present when video is queued for YouTube
  message?:  string
}

export interface RerunResult {
  success:  boolean
  message?: string
}

// Excel preview row (client-side only)
export interface PreviewRow {
  prompt:       string
  duration:     number
  aspect_ratio?: string
  task_type?:   string
  priority?:    number
}

// ── Refinement overlay types ──────────────────────────────────────────────────

export interface StructuredFields {
  scene:          string
  characters:     string
  camera:         string
  narrationLines: string[]
  lighting:       string
  mythologyNotes: string
}

export interface ClipTimestamp {
  clip:       number
  durationS:  number
  startS:     number
  endS:       number
  endState:   string
  prompt:     string   // populated in Mode 2 only
  label:      string   // "Clip 1 · 0–8s"
}

export interface RefinedRow {
  rowIndex:          number
  rowNumber:         number
  originalPrompt:    string
  refinedPrompt:     string
  mythologyDetected: boolean
  warnings:          string[]
  structured:        StructuredFields
  clips:             ClipTimestamp[]
  nClips:            number
  duration:          number
  clipsReady:        boolean   // true in Mode 2 — decomposition already done
}

export interface RefineResponse {
  jobId:       string
  totalRows:   number
  mode:        GenerationMode
  refinerMode: number
  rows:        RefinedRow[]
}

// Per-row edit state maintained independently in the overlay
export interface RowEditState {
  rowIndex:      number
  // Two independent edit states — never sync with each other
  freeText:      string
  freeTextDirty: boolean
  structured:    StructuredFields
  structuredDirty: boolean
  // Which version to send on approve: refined | freetext | structured
  activeVersion: 'refined' | 'freetext' | 'structured'
  editMode:      'freetext' | 'structured'
  isExpanded:    boolean
  isRefining:    boolean   // per-card "Refine Again" spinner
}