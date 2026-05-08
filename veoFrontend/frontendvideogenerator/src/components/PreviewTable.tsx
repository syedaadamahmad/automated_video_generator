// // src/components/PreviewTable.tsx
// 'use client'
// import { Tooltip } from './Tooltip'
// import type { PreviewRow } from '@/types'

// interface Props {
//   rows: PreviewRow[]
// }

// const TASK_COLORS: Record<string, string> = {
//   AUTO:                 '#0071E3',
//   TEXT_VIDEO:           '#34C759',
//   MULTI_SHOT_AUTOMATED: '#FF9F0A',
// }

// export function PreviewTable({ rows }: Props) {
//   const preview = rows.slice(0, 20)

//   return (
//     <div
//       style={{
//         background: 'var(--surface)',
//         border: '1px solid var(--border2)',
//         borderRadius: 'var(--radius-lg)',
//         overflow: 'hidden',
//         marginTop: '1.25rem',
//       }}
//     >
//       {/* Caption */}
//       <div
//         style={{
//           fontSize: 11,
//           fontWeight: 600,
//           letterSpacing: '.04em',
//           textTransform: 'uppercase',
//           color: 'var(--text2)',
//           padding: '8px 16px',
//           background: 'var(--surface2)',
//           borderBottom: '1px solid var(--border2)',
//         }}
//       >
//         Preview — {preview.length} of {rows.length} row{rows.length !== 1 ? 's' : ''}
//       </div>

//       <div style={{ overflowX: 'auto' }}>
//         <table className="veo-table">
//           <thead>
//             <tr>
//               <th style={{ minWidth: 320 }}>
//                 Prompt
//                 <Tooltip text="The master prompt. Include NARRATOR:, GROUP ANCHOR:, SCENE ANCHOR: and narration lines for best results." />
//               </th>
//               <th>
//                 Duration
//                 <Tooltip text="Total video length in seconds. Must be a multiple of 8. E.g. 8, 16, 24, 32." />
//               </th>
//               <th>Clips</th>
//               <th>
//                 Aspect
//                 <Tooltip text="Set globally in veo.env. 9:16 for portrait (Reels), 16:9 for landscape (YouTube)." />
//               </th>
//               <th>
//                 Task type
//                 <Tooltip text="AUTO = platform decides. TEXT_VIDEO = force single clip. MULTI_SHOT_AUTOMATED = force decomposition." />
//               </th>
//               <th>
//                 Priority
//                 <Tooltip text="1–10. Lower number = generated first. Useful when you have limited daily quota." />
//               </th>
//             </tr>
//           </thead>
//           <tbody>
//             {preview.map((row, i) => {
//               const clips  = Math.ceil((row.duration || 8) / 8)
//               const task   = (row.task_type ?? 'AUTO').toUpperCase()
//               const tc     = TASK_COLORS[task] ?? 'var(--text2)'
//               const prompt = row.prompt ?? ''

//               return (
//                 <tr key={i}>
//                   <td>
//                     <div
//                       style={{
//                         maxWidth: 380,
//                         whiteSpace: 'nowrap',
//                         overflow: 'hidden',
//                         textOverflow: 'ellipsis',
//                         fontSize: 13,
//                       }}
//                       title={prompt}
//                     >
//                       {prompt.length > 120 ? prompt.slice(0, 120) + '…' : prompt}
//                     </div>
//                   </td>
//                   <td style={{ whiteSpace: 'nowrap' }}>{row.duration ?? 8}s</td>
//                   <td>{clips}</td>
//                   <td style={{ whiteSpace: 'nowrap' }}>{row.aspect_ratio ?? '—'}</td>
//                   <td>
//                     <span
//                       style={{
//                         display: 'inline-block',
//                         fontSize: 11,
//                         fontWeight: 500,
//                         padding: '2px 8px',
//                         borderRadius: 20,
//                         border: `1px solid ${tc}40`,
//                         color: tc,
//                         background: `${tc}10`,
//                       }}
//                     >
//                       {task}
//                     </span>
//                   </td>
//                   <td>{row.priority ?? 5}</td>
//                 </tr>
//               )
//             })}
//           </tbody>
//         </table>
//       </div>
//     </div>
//   )
// }





















// src/components/PreviewTable.tsx
'use client'
import { Tooltip } from './Tooltip'
import type { PreviewRow } from '@/types'

interface Props {
  rows:          PreviewRow[]
  mode?:         'full' | 'short_span' | 'short_span_image'
  clipDuration?: number
}

const TASK_COLORS: Record<string, string> = {
  AUTO:                 '#0071E3',
  TEXT_VIDEO:           '#34C759',
  MULTI_SHOT_AUTOMATED: '#FF9F0A',
}

export function PreviewTable({ rows, mode = 'full', clipDuration = 2 }: Props) {
  const preview = rows.slice(0, 20)

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border2)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        marginTop: '1.25rem',
      }}
    >
      {/* Caption */}
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '.04em',
          textTransform: 'uppercase',
          color: 'var(--text2)',
          padding: '8px 16px',
          background: 'var(--surface2)',
          borderBottom: '1px solid var(--border2)',
        }}
      >
        Preview — {preview.length} of {rows.length} row{rows.length !== 1 ? 's' : ''}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="veo-table">
          <thead>
            <tr>
              <th style={{ minWidth: 320 }}>
                Prompt
                <Tooltip text="The master prompt. Include NARRATOR:, GROUP ANCHOR:, SCENE ANCHOR: and narration lines for best results." />
              </th>
              <th>
                Duration
                <Tooltip text="Total video length in seconds. Must be a multiple of 8. E.g. 8, 16, 24, 32." />
              </th>
              <th>Clips</th>
              <th>
                Aspect
                <Tooltip text="Set globally in veo.env. 9:16 for portrait (Reels), 16:9 for landscape (YouTube)." />
              </th>
              <th>
                Task type
                <Tooltip text="AUTO = platform decides. TEXT_VIDEO = force single clip. MULTI_SHOT_AUTOMATED = force decomposition." />
              </th>
              <th>
                Priority
                <Tooltip text="1–10. Lower number = generated first. Useful when you have limited daily quota." />
              </th>
            </tr>
          </thead>
          <tbody>
            {preview.map((row, i) => {
              const isShortSpan = mode === 'short_span' || mode === 'short_span_image'
              // In short span mode, duration and clips come from the UI, not the Excel
              const displayDur   = isShortSpan ? clipDuration : (row.duration ?? 8)
              const displayClips = isShortSpan ? 1 : Math.ceil((row.duration || 8) / 8)
              const task   = (row.task_type ?? 'AUTO').toUpperCase()
              const tc     = TASK_COLORS[task] ?? 'var(--text2)'
              const prompt = row.prompt ?? ''

              return (
                <tr key={i}>
                  <td>
                    <div
                      style={{
                        maxWidth: 380,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        fontSize: 13,
                      }}
                      title={prompt}
                    >
                      {prompt.length > 120 ? prompt.slice(0, 120) + '…' : prompt}
                    </div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap', color: isShortSpan ? 'var(--accent)' : 'var(--text)' }}>
                    {displayDur}s{isShortSpan ? ' ✎' : ''}
                  </td>
                  <td>{displayClips}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{row.aspect_ratio ?? '—'}</td>
                  <td>
                    {isShortSpan
                      ? <span style={{ fontSize: 11, color: 'var(--text3)' }}>—</span>
                      : <span style={{ display: 'inline-block', fontSize: 11, fontWeight: 500,
                          padding: '2px 8px', borderRadius: 20,
                          border: `1px solid ${tc}40`, color: tc, background: `${tc}10` }}>
                          {task}
                        </span>
                    }
                  </td>
                  <td style={{ color: isShortSpan ? 'var(--text3)' : 'var(--text)' }}>
                    {isShortSpan ? '—' : (row.priority ?? 5)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}