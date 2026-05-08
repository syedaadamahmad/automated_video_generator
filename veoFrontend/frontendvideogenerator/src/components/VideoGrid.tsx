// // src/components/VideoGrid.tsx
// 'use client'
// import { VideoCard } from './VideoCard'
// import { SkeletonCard } from './SkeletonCard'
// import { Tooltip } from './Tooltip'
// import type { Job } from '@/types'
// import type { Role } from '@/types'

// interface Props {
//   job:      Job
//   role:     Role
//   rejected: Set<string>     // Set of `${jobId}-${index}`
//   onReject: (jobId: string, index: number) => void
//   onRerun:  () => void
// }

// export function VideoGrid({ job, role, rejected, onReject, onRerun }: Props) {
//   const prompts = job.prompts ?? []
//   if (!prompts.length) return null

//   return (
//     <section style={{ marginTop: '2.5rem' }}>
//       <div
//         style={{
//           display: 'flex',
//           alignItems: 'center',
//           gap: 6,
//           marginBottom: '1.25rem',
//         }}
//       >
//         <h2
//           style={{
//             fontSize: 22,
//             fontWeight: 600,
//             letterSpacing: '-0.025em',
//             color: 'var(--text)',
//           }}
//         >
//           Generated Videos
//         </h2>
//         <Tooltip text="Cards appear as each prompt completes. Rejected cards are removed from this view only — videos remain on disk and S3." />
//       </div>

//       <div
//         style={{
//           display: 'grid',
//           gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
//           gap: '1.25rem',
//         }}
//       >
//         {prompts.map((p, i) => {
//           const key = `${job.job_id}-${i}`
//           if (rejected.has(key)) return null

//           if (p.status === 'completed' || p.status === 'partial') {
//             return (
//               <VideoCard
//                 key={key}
//                 prompt={p}
//                 jobId={job.job_id}
//                 index={i}
//                 role={role}
//                 onReject={onReject}
//                 onRerun={onRerun}
//               />
//             )
//           }

//           // processing / pending / failed → skeleton
//           return <SkeletonCard key={key} />
//         })}
//       </div>
//     </section>
//   )
// }





























// src/components/VideoGrid.tsx
'use client'
import { VideoCard }    from './VideoCard'
import { SkeletonCard } from './SkeletonCard'
import { Tooltip }      from './Tooltip'
import type { Job, GenerationMode, Prompt } from '@/types'
import type { Role } from '@/types'

interface Props {
  job:      Job
  role:     Role
  rejected: Set<string>     // Set of `${jobId}-${index}`
  onReject: (jobId: string, index: number) => void
  onRerun:  () => void
}

export function VideoGrid({ job, role, rejected, onReject, onRerun }: Props) {
  const prompts: Prompt[]      = job.prompts ?? []
  const jobId:   string        = job.job_id
  const mode:    GenerationMode = job.mode ?? 'full'
  const isShortSpan             = mode === 'short_span' || mode === 'short_span_image'

  if (!prompts.length) return null

  const heading = mode === 'short_span_image'
    ? 'Image Slideshow'
    : isShortSpan
    ? 'Short Span Sequence'
    : 'Generated Videos'

  const tooltip = mode === 'short_span_image'
    ? 'All rows were generated as static images with Ken Burns animation and crossfaded into one silent slideshow video.'
    : isShortSpan
    ? 'All rows were combined into one stitched short-span sequence. One card per job.'
    : 'Cards appear as each prompt completes. Rejected cards are removed from this view only — videos remain on disk and S3.'

  return (
    <section style={{ marginTop: '2.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: '1.25rem' }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.025em', color: 'var(--text)' }}>
          {heading}
        </h2>
        <Tooltip text={tooltip} />
      </div>

      {/* ── Short Span Mode: single stitched result card ── */}
      {isShortSpan ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1.25rem' }}>
          {(() => {
            const key = `${jobId}-0`
            if (rejected.has(key)) return null

            // Backend always stores the stitched result at index 0 for short span modes
            const result: Prompt | undefined = prompts[0]
            const jobStatus = job.status

            // Job still running — show skeleton
            if (jobStatus === 'processing' || jobStatus === 'pending') {
              return <SkeletonCard key="ss-skeleton" />
            }

            // Job complete — show stitched card
            if (result && (result.status === 'completed' || result.status === 'partial')) {
              return (
                <VideoCard
                  key={key}
                  prompt={result}
                  jobId={jobId}
                  index={0}
                  role={role}
                  onReject={onReject}
                  onRerun={onRerun}
                />
              )
            }

            // Failed
            return (
              <div key="ss-failed" style={{
                background: 'var(--surface)', border: '1px solid var(--border2)',
                borderRadius: 'var(--radius-lg)', padding: '2rem 1.5rem',
                textAlign: 'center', color: 'var(--error)', fontSize: 13,
              }}>
                Generation failed — check veo_main.py logs.
              </div>
            )
          })()}
        </div>
      ) : (
        /* ── Full Length Mode: one card per prompt ── */
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1.25rem' }}>
          {prompts.map((p: Prompt, i: number) => {
            const key = `${jobId}-${i}`
            if (rejected.has(key)) return null

            if (p.status === 'completed' || p.status === 'partial') {
              return (
                <VideoCard
                  key={key}
                  prompt={p}
                  jobId={jobId}
                  index={i}
                  role={role}
                  onReject={onReject}
                  onRerun={onRerun}
                />
              )
            }
            return <SkeletonCard key={key} />
          })}
        </div>
      )}
    </section>
  )
}