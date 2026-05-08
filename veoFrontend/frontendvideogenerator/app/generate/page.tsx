// // src/app/generate/page.tsx
// 'use client'
// import { useState, useEffect, useRef, useCallback } from 'react'
// import { useSession } from 'next-auth/react'
// import { useRouter } from 'next/navigation'
// import useSWR from 'swr'
// import { read, utils } from 'xlsx'

// import { Navbar }       from '@/components/Navbar'
// import { UploadZone, SectionLabel } from '@/components/UploadZone'
// import { PreviewTable } from '@/components/PreviewTable'
// import { VideoGrid }    from '@/components/VideoGrid'
// import { JobsPanel }    from '@/components/JobsPanel'
// import { MetricsPanel } from '@/components/MetricsPanel'
// import { YouTubeQueue } from '@/components/YouTubeQueue'
// import { Tooltip }      from '@/components/Tooltip'

// import { checkHealth, uploadFile, fetchJob } from '@/lib/api'
// import { hasPermission } from '@/lib/permissions'
// import type { Role } from '@/types'
// import type { Job, PreviewRow } from '@/types'

// // ── Sample xlsx generation (client-side) ────────────────────────────────────
// async function downloadSample() {
//   const { utils: xlsxUtils, writeFile } = await import('xlsx')
//   const wb = xlsxUtils.book_new()
//   const ws = xlsxUtils.aoa_to_sheet([
//     ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
//     [
//       'NARRATOR: warm, Indian-accented female voice, calm and confident\n\n'
//       + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops.\n'
//       + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon desks, large windows, daytime.\n'
//       + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level.\n\n'
//       + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.\n\n'
//       + 'Indian Accent Narration: "The future belongs to creators, not just users."\n\n'
//       + 'Students at glowing desks, experimenting with AI tools and laptops.\n\n'
//       + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."\n\n'
//       + 'Fast montage: AI artwork on screen, chatbot on phone, student designing website.\n\n'
//       + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."\n\n'
//       + 'Confident student presenting to classmates, applauding, scene holds still.\n\n'
//       + 'Indian Accent Narration: "Start your AI journey today."',
//       32, '9:16', 'AUTO', 1,
//     ],
//     [
//       'NARRATOR: calm, professional Indian male voice\n\n'
//       + 'Corporate professionals in a modern boardroom, AI analytics on screens.\n\n'
//       + 'Narration: "What if your whole organisation could think smarter?"\n\n'
//       + 'Team reviewing AI dashboards, confident expressions, collaborative energy.\n\n'
//       + 'Narration: "AI training for every leader, every team."\n\n'
//       + 'Team smiling, city skyline behind them, scene holds still.\n\n'
//       + 'Narration: "Build the future with your people."',
//       24, '16:9', 'AUTO', 2,
//     ],
//     [
//       'NARRATOR: energetic young Indian female voice\n'
//       + 'STATIC shot of Indian student at clean desk, laptop open, soft window light.\n\n'
//       + 'Narration: "One course. Unlimited possibilities."\n\n'
//       + 'Student smiles at camera, holds laptop up confidently, scene holds.',
//       8, '9:16', 'TEXT_VIDEO', 3,
//     ],
//   ])
//   ws['!cols'] = [{ wch: 80 }, { wch: 12 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
//   xlsxUtils.book_append_sheet(wb, ws, 'prompts')
//   writeFile(wb, 'veo_sample_prompts.xlsx')
// }

// // ── Parse Excel to preview rows ──────────────────────────────────────────────
// function parseExcel(file: File): Promise<PreviewRow[]> {
//   return new Promise((resolve, reject) => {
//     const reader = new FileReader()
//     reader.onload = e => {
//       try {
//         const data   = e.target?.result
//         const wb     = read(data, { type: 'array' })
//         const ws     = wb.Sheets[wb.SheetNames[0]]
//         const raw    = utils.sheet_to_json(ws, { defval: '' }) as any[]
//         // Normalise column names
//         const rows: PreviewRow[] = raw
//           .map(r => {
//             const lower: any = {}
//             for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
//             const dur = parseFloat(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
//             return {
//               prompt:       String(lower['prompt'] ?? '').trim(),
//               duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
//               aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
//               task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
//               priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
//             }
//           })
//           .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
//         resolve(rows)
//       } catch (err) {
//         reject(err)
//       }
//     }
//     reader.onerror = reject
//     reader.readAsArrayBuffer(file)
//   })
// }

// type Tab = 'generate' | 'youtube' | 'data'

// // ── Page ─────────────────────────────────────────────────────────────────────
// export default function GeneratePage() {
//   const { data: session, status } = useSession()
//   const router = useRouter()
//   const role   = ((session?.user as any)?.role ?? 'viewer') as Role

//   // Redirect unauthenticated
//   useEffect(() => {
//     if (status === 'unauthenticated') router.push('/login')
//   }, [status, router])

//   const [tab, setTab]             = useState<Tab>('generate')
//   const [apiOk, setApiOk]         = useState<boolean | null>(null)
//   const [file, setFile]           = useState<File | null>(null)
//   const [preview, setPreview]     = useState<PreviewRow[]>([])
//   const [parseErr, setParseErr]   = useState('')
//   const [generating, setGenerating] = useState(false)
//   const [uploadErr, setUploadErr] = useState('')

//   // Active job state
//   const [activeJobId, setActiveJobId]     = useState<string | null>(null)
//   const [lastJobId, setLastJobId]         = useState<string | null>(null)
//   const [rejected, setRejected]           = useState<Set<string>>(new Set())

//   // Polling
//   const displayJobId = activeJobId ?? lastJobId
//   const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
//     displayJobId ? `job-${displayJobId}` : null,
//     () => fetchJob(displayJobId!),
//     {
//       refreshInterval: activeJobId ? 4000 : 0,
//       onSuccess(job) {
//         if (!['processing', 'pending'].includes(job.status)) {
//           setLastJobId(job.job_id)
//           setActiveJobId(null)
//           setGenerating(false)
//         }
//       },
//     },
//   )

//   // Video grid anchor ref for smooth scroll on generation start
//   const gridRef = useRef<HTMLDivElement>(null)
//   useEffect(() => {
//     if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
//   }, [activeJobId])

//   // API health check on mount
//   useEffect(() => {
//     checkHealth().then(ok => setApiOk(ok))
//   }, [])

//   async function handleFile(f: File) {
//     setFile(f)
//     setParseErr('')
//     setPreview([])
//     try {
//       const rows = await parseExcel(f)
//       setPreview(rows)
//     } catch (e: any) {
//       setParseErr(`Could not parse file: ${e.message}`)
//     }
//   }

//   async function handleGenerate() {
//     if (!file || generating) return
//     setGenerating(true)
//     setUploadErr('')
//     setRejected(new Set())

//     try {
//       const result = await uploadFile(file)
//       setActiveJobId(result.job_id)
//     } catch (e: any) {
//       setUploadErr(`Upload failed: ${e.message}`)
//       setGenerating(false)
//     }
//   }

//   function handleReject(jobId: string, index: number) {
//     setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
//   }

//   const totalClips = preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
//   const totalDur   = preview.reduce((a, r) => a + (r.duration || 8), 0)

//   if (status === 'loading') return null

//   return (
//     <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
//       <Navbar />

//       {/* Tab bar */}
//       <div
//         style={{
//           borderBottom: '1px solid var(--border)',
//           padding: '0 2rem',
//           display: 'flex',
//           gap: 0,
//         }}
//       >
//         {([
//           ['generate', 'Generate'],
//           ['youtube',  'YouTube Queue'],
//           ['data',     'Jobs & Metrics'],
//         ] as [Tab, string][]).map(([id, label]) => (
//           <button
//             key={id}
//             onClick={() => setTab(id)}
//             style={{
//               fontSize: 13.5,
//               fontWeight: 500,
//               padding: '10px 16px',
//               background: 'none',
//               border: 'none',
//               borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
//               color: tab === id ? 'var(--text)' : 'var(--text2)',
//               cursor: 'pointer',
//               fontFamily: 'inherit',
//               transition: 'color .15s',
//             }}
//           >
//             {label}
//           </button>
//         ))}
//       </div>

//       {/* Content */}
//       <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

//         {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
//         {tab === 'generate' && (
//           <>
//             {/* API status */}
//             {apiOk === false && (
//               <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
//                 ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
//               </div>
//             )}

//             {/* Upload section */}
//             <div style={{ marginBottom: '1.75rem' }}>
//               <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
//                 <SectionLabel tooltip="Upload an Excel file with your video prompts. Each row = one ad. The platform decomposes multi-clip ads automatically.">
//                   Upload prompts
//                 </SectionLabel>
//                 <button
//                   onClick={downloadSample}
//                   style={{
//                     fontSize: 12.5,
//                     fontWeight: 500,
//                     padding: '6px 14px',
//                     borderRadius: 'var(--pill)',
//                     border: '1px solid var(--border)',
//                     background: 'none',
//                     color: 'var(--text2)',
//                     cursor: 'pointer',
//                     fontFamily: 'inherit',
//                   }}
//                 >
//                   ↓ Sample Excel
//                 </button>
//               </div>
//               <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
//                 Excel file with <code>prompt</code>, <code>duration</code>, <code>aspect_ratio</code>, <code>task_type</code> and <code>priority</code> columns.
//               </p>
//               <UploadZone onFile={handleFile} disabled={generating} />
//               {parseErr && (
//                 <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
//               )}
//             </div>

//             {/* Preview table */}
//             {preview.length > 0 && (
//               <>
//                 <PreviewTable rows={preview} />

//                 {/* Generate CTA */}
//                 <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
//                   {hasPermission(role, 'generate') ? (
//                     <button
//                       onClick={handleGenerate}
//                       disabled={generating || !file}
//                       style={{
//                         background: 'var(--text)',
//                         color: 'var(--bg)',
//                         border: 'none',
//                         borderRadius: 'var(--pill)',
//                         padding: '10px 28px',
//                         fontSize: 15,
//                         fontWeight: 600,
//                         cursor: generating ? 'not-allowed' : 'pointer',
//                         opacity: generating ? 0.45 : 1,
//                         fontFamily: 'inherit',
//                         transition: 'opacity .15s',
//                         display: 'flex',
//                         alignItems: 'center',
//                         gap: 8,
//                       }}
//                     >
//                       {generating ? 'Generating…' : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
//                     </button>
//                   ) : (
//                     <div className="alert alert-warn" style={{ margin: 0 }}>
//                       ⚠️  Your role cannot generate videos.
//                     </div>
//                   )}
//                   {!generating && preview.length > 0 && (
//                     <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
//                       {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
//                     </span>
//                   )}
//                   {uploadErr && (
//                     <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
//                   )}
//                 </div>
//               </>
//             )}

//             {/* Video grid */}
//             <div ref={gridRef}>
//               {liveJob && (
//                 <VideoGrid
//                   job={liveJob}
//                   role={role}
//                   rejected={rejected}
//                   onReject={handleReject}
//                   onRerun={() => refetchJob()}
//                 />
//               )}
//             </div>
//           </>
//         )}

//         {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
//         {tab === 'youtube' && (
//           <>
//             <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
//               YouTube Queue
//             </SectionLabel>
//             <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
//               Approve a video card on the Generate tab to add it here.
//             </p>
//             <YouTubeQueue role={role} />
//           </>
//         )}

//         {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
//         {tab === 'data' && (
//           <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
//             {hasPermission(role, 'view_jobs') && <JobsPanel />}
//             {hasPermission(role, 'view_metrics') && <MetricsPanel />}
//             {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
//               <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
//             )}
//           </div>
//         )}
//       </main>
//     </div>
//   )
// }























// // src/app/generate/page.tsx
// 'use client'
// import { useState, useEffect, useRef, useCallback } from 'react'
// import { useSession } from 'next-auth/react'
// import { useRouter } from 'next/navigation'
// import useSWR from 'swr'
// import { read, utils } from 'xlsx'

// import { Navbar }       from '@/components/Navbar'
// import { UploadZone, SectionLabel } from '@/components/UploadZone'
// import { PreviewTable } from '@/components/PreviewTable'
// import { VideoGrid }    from '@/components/VideoGrid'
// import { JobsPanel }    from '@/components/JobsPanel'
// import { MetricsPanel } from '@/components/MetricsPanel'
// import { YouTubeQueue } from '@/components/YouTubeQueue'
// import { Tooltip }      from '@/components/Tooltip'

// import { checkHealth, uploadFile, fetchJob } from '@/lib/api'
// import { hasPermission } from '@/lib/permissions'
// import type { Role } from '@/types'
// import type { Job, PreviewRow } from '@/types'

// // ── Sample xlsx generation (client-side) ────────────────────────────────────
// async function downloadSample() {
//   const { utils: xlsxUtils, writeFile } = await import('xlsx')
//   const wb = xlsxUtils.book_new()
//   const ws = xlsxUtils.aoa_to_sheet([
//     ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
//     [
//       'NARRATOR: warm, Indian-accented female voice, calm and confident\n\n'
//       + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops.\n'
//       + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon desks, large windows, daytime.\n'
//       + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level.\n\n'
//       + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.\n\n'
//       + 'Indian Accent Narration: "The future belongs to creators, not just users."\n\n'
//       + 'Students at glowing desks, experimenting with AI tools and laptops.\n\n'
//       + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."\n\n'
//       + 'Fast montage: AI artwork on screen, chatbot on phone, student designing website.\n\n'
//       + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."\n\n'
//       + 'Confident student presenting to classmates, applauding, scene holds still.\n\n'
//       + 'Indian Accent Narration: "Start your AI journey today."',
//       32, '9:16', 'AUTO', 1,
//     ],
//     [
//       'NARRATOR: calm, professional Indian male voice\n\n'
//       + 'Corporate professionals in a modern boardroom, AI analytics on screens.\n\n'
//       + 'Narration: "What if your whole organisation could think smarter?"\n\n'
//       + 'Team reviewing AI dashboards, confident expressions, collaborative energy.\n\n'
//       + 'Narration: "AI training for every leader, every team."\n\n'
//       + 'Team smiling, city skyline behind them, scene holds still.\n\n'
//       + 'Narration: "Build the future with your people."',
//       24, '16:9', 'AUTO', 2,
//     ],
//     [
//       'NARRATOR: energetic young Indian female voice\n'
//       + 'STATIC shot of Indian student at clean desk, laptop open, soft window light.\n\n'
//       + 'Narration: "One course. Unlimited possibilities."\n\n'
//       + 'Student smiles at camera, holds laptop up confidently, scene holds.',
//       8, '9:16', 'TEXT_VIDEO', 3,
//     ],
//   ])
//   ws['!cols'] = [{ wch: 80 }, { wch: 12 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
//   xlsxUtils.book_append_sheet(wb, ws, 'prompts')
//   writeFile(wb, 'veo_sample_prompts.xlsx')
// }

// // ── Parse Excel to preview rows ──────────────────────────────────────────────
// function parseExcel(file: File): Promise<PreviewRow[]> {
//   return new Promise((resolve, reject) => {
//     const reader = new FileReader()
//     reader.onload = e => {
//       try {
//         const data   = e.target?.result
//         const wb     = read(data, { type: 'array' })
//         const ws     = wb.Sheets[wb.SheetNames[0]]
//         const raw    = utils.sheet_to_json(ws, { defval: '' }) as any[]
//         // Normalise column names
//         const rows: PreviewRow[] = raw
//           .map(r => {
//             const lower: any = {}
//             for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
//             const dur = parseFloat(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
//             return {
//               prompt:       String(lower['prompt'] ?? '').trim(),
//               duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
//               aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
//               task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
//               priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
//             }
//           })
//           .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
//         resolve(rows)
//       } catch (err) {
//         reject(err)
//       }
//     }
//     reader.onerror = reject
//     reader.readAsArrayBuffer(file)
//   })
// }

// type Tab = 'generate' | 'youtube' | 'data'

// // ── Page ─────────────────────────────────────────────────────────────────────
// export default function GeneratePage() {
//   const { data: session, status } = useSession()
//   const router = useRouter()
//   const role   = ((session?.user as any)?.role ?? 'viewer') as Role

//   // Redirect unauthenticated
//   useEffect(() => {
//     if (status === 'unauthenticated') router.push('/login')
//   }, [status, router])

//   const [tab, setTab]             = useState<Tab>('generate')
//   const [apiOk, setApiOk]         = useState<boolean | null>(null)
//   const [file, setFile]           = useState<File | null>(null)
//   const [preview, setPreview]     = useState<PreviewRow[]>([])
//   const [parseErr, setParseErr]   = useState('')
//   const [generating, setGenerating] = useState(false)
//   const [uploadErr, setUploadErr]   = useState('')

//   // Mode / feature toggles — placed before upload so user sets them first
//   const [mode, setMode]               = useState<'full' | 'short_span'>('full')
//   const [clipDuration, setClipDuration] = useState<number>(2)
//   const [noText, setNoText]           = useState(false)
//   const [noSpeech, setNoSpeech]       = useState(false)

//   // Active job state
//   const [activeJobId, setActiveJobId]     = useState<string | null>(null)
//   const [lastJobId, setLastJobId]         = useState<string | null>(null)
//   const [rejected, setRejected]           = useState<Set<string>>(new Set())

//   // Polling
//   const displayJobId = activeJobId ?? lastJobId
//   const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
//     displayJobId ? `job-${displayJobId}` : null,
//     () => fetchJob(displayJobId!),
//     {
//       refreshInterval: activeJobId ? 4000 : 0,
//       onSuccess(job) {
//         if (!['processing', 'pending'].includes(job.status)) {
//           setLastJobId(job.job_id)
//           setActiveJobId(null)
//           setGenerating(false)
//           // Final refetch after a short delay ensures all prompt results are
//           // included — the job may flip to "completed" slightly before the
//           // last result is written into the jobs dict.
//           setTimeout(() => refetchJob(), 1500)
//         }
//       },
//     },
//   )

//   // Video grid anchor ref for smooth scroll on generation start
//   const gridRef = useRef<HTMLDivElement>(null)
//   useEffect(() => {
//     if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
//   }, [activeJobId])

//   // API health check on mount
//   useEffect(() => {
//     checkHealth().then(ok => setApiOk(ok))
//   }, [])

//   async function handleFile(f: File) {
//     setFile(f)
//     setParseErr('')
//     setPreview([])
//     try {
//       const rows = await parseExcel(f)
//       setPreview(rows)
//     } catch (e: any) {
//       setParseErr(`Could not parse file: ${e.message}`)
//     }
//   }

//   async function handleGenerate() {
//     if (!file || generating) return
//     setGenerating(true)
//     setUploadErr('')
//     setRejected(new Set())

//     try {
//       const result = await uploadFile(file, {
//         mode,
//         clipDuration,
//         noText,
//         noSpeech,
//       })
//       setActiveJobId(result.job_id)
//     } catch (e: any) {
//       setUploadErr(`Upload failed: ${e.message}`)
//       setGenerating(false)
//     }
//   }

//   function handleReject(jobId: string, index: number) {
//     setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
//   }

//   const totalClips = preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
//   const totalDur   = preview.reduce((a, r) => a + (r.duration || 8), 0)

//   if (status === 'loading') return null

//   return (
//     <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
//       <Navbar />

//       {/* Tab bar */}
//       <div
//         style={{
//           borderBottom: '1px solid var(--border)',
//           padding: '0 2rem',
//           display: 'flex',
//           gap: 0,
//         }}
//       >
//         {([
//           ['generate', 'Generate'],
//           ['youtube',  'YouTube Queue'],
//           ['data',     'Jobs & Metrics'],
//         ] as [Tab, string][]).map(([id, label]) => (
//           <button
//             key={id}
//             onClick={() => setTab(id)}
//             style={{
//               fontSize: 13.5,
//               fontWeight: 500,
//               padding: '10px 16px',
//               background: 'none',
//               border: 'none',
//               borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
//               color: tab === id ? 'var(--text)' : 'var(--text2)',
//               cursor: 'pointer',
//               fontFamily: 'inherit',
//               transition: 'color .15s',
//             }}
//           >
//             {label}
//           </button>
//         ))}
//       </div>

//       {/* Content */}
//       <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

//         {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
//         {tab === 'generate' && (
//           <>
//             {/* API status */}
//             {apiOk === false && (
//               <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
//                 ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
//               </div>
//             )}

//             {/* ── Mode & options — set BEFORE uploading ── */}
//             <div style={{
//               background: 'var(--surface)',
//               border: '1px solid var(--border2)',
//               borderRadius: 'var(--radius-lg)',
//               padding: '1.25rem 1.5rem',
//               marginBottom: '1.5rem',
//               display: 'flex',
//               flexDirection: 'column',
//               gap: '1rem',
//             }}>
//               {/* Mode toggle */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                 <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                   Generation mode
//                 </span>
//                 <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                   border: '1px solid var(--border)' }}>
//                   {(['full', 'short_span'] as const).map(m => (
//                     <button key={m} onClick={() => setMode(m)} style={{
//                       padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                       background: mode === m ? 'var(--text)' : 'none',
//                       color: mode === m ? 'var(--bg)' : 'var(--text2)',
//                       border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                     }}>
//                       {m === 'full' ? 'Full Length Videos' : 'Short Span Clips'}
//                     </button>
//                   ))}
//                 </div>
//                 <Tooltip text={mode === 'full'
//                   ? 'Full pipeline: decomposition, multi-clip generation, img2vid chaining, stitching. Each Excel row = one full ad.'
//                   : 'Each Excel row = one discrete clip sent directly to Veo. No decomposition — you control each clip. Clips are chained and stitched into one video.'
//                 } />
//               </div>

//               {/* Clip duration — short_span only */}
//               {mode === 'short_span' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 3, 4, 5, 6, 8].map(d => (
//                       <button key={d} onClick={() => setClipDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: clipDuration === d ? 'var(--text)' : 'none',
//                         color: clipDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="Duration per clip sent to Veo (2–8 seconds). Total video = number of Excel rows × clip duration." />
//                 </div>
//               )}

//               {/* No text / No speech */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
//                 {([
//                   {
//                     key: 'noText',
//                     label: 'No text overlay',
//                     tooltip: 'Injects a guardrail instructing Veo to not render any text, captions, titles, subtitles, or watermarks in the video frame.',
//                     val: noText,
//                     set: setNoText,
//                   },
//                   {
//                     key: 'noSpeech',
//                     label: 'No speech / narration',
//                     tooltip: 'Suppresses all lip movement, narration, and dialogue. Ambient background audio is preserved. Use when you want to add your own voiceover or music in post.',
//                     val: noSpeech,
//                     set: setNoSpeech,
//                   },
//                 ] as const).map(({ key, label, tooltip, val, set }) => (
//                   <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 8,
//                     cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
//                     <input
//                       type="checkbox"
//                       checked={val}
//                       onChange={e => (set as (v: boolean) => void)(e.target.checked)}
//                       style={{ width: 15, height: 15, cursor: 'pointer', accentColor: 'var(--text)' }}
//                     />
//                     {label}
//                     <Tooltip text={tooltip} />
//                   </label>
//                 ))}
//               </div>
//             </div>

//             {/* Upload section */}
//             <div style={{ marginBottom: '1.75rem' }}>
//               <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
//                 <SectionLabel tooltip="Upload an Excel file with your video prompts. Each row = one ad. The platform decomposes multi-clip ads automatically.">
//                   Upload prompts
//                 </SectionLabel>
//                 <button
//                   onClick={downloadSample}
//                   style={{
//                     fontSize: 12.5,
//                     fontWeight: 500,
//                     padding: '6px 14px',
//                     borderRadius: 'var(--pill)',
//                     border: '1px solid var(--border)',
//                     background: 'none',
//                     color: 'var(--text2)',
//                     cursor: 'pointer',
//                     fontFamily: 'inherit',
//                   }}
//                 >
//                   ↓ Sample Excel
//                 </button>
//               </div>
//               <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
//                 Excel file with <code>prompt</code>, <code>duration</code>, <code>aspect_ratio</code>, <code>task_type</code> and <code>priority</code> columns.
//               </p>
//               <UploadZone onFile={handleFile} disabled={generating} />
//               {parseErr && (
//                 <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
//               )}
//             </div>

//             {/* Preview table */}
//             {preview.length > 0 && (
//               <>
//                 <PreviewTable rows={preview} />

//                 {/* Generate CTA */}
//                 <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
//                   {hasPermission(role, 'generate') ? (
//                     <button
//                       onClick={handleGenerate}
//                       disabled={generating || !file}
//                       style={{
//                         background: 'var(--text)',
//                         color: 'var(--bg)',
//                         border: 'none',
//                         borderRadius: 'var(--pill)',
//                         padding: '10px 28px',
//                         fontSize: 15,
//                         fontWeight: 600,
//                         cursor: generating ? 'not-allowed' : 'pointer',
//                         opacity: generating ? 0.45 : 1,
//                         fontFamily: 'inherit',
//                         transition: 'opacity .15s',
//                         display: 'flex',
//                         alignItems: 'center',
//                         gap: 8,
//                       }}
//                     >
//                       {generating
//                         ? 'Generating…'
//                         : mode === 'short_span'
//                         ? `▶  Generate  ·  ${preview.length} clip${preview.length !== 1 ? 's' : ''} · ${preview.length * clipDuration}s total`
//                         : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
//                     </button>
//                   ) : (
//                     <div className="alert alert-warn" style={{ margin: 0 }}>
//                       ⚠️  Your role cannot generate videos.
//                     </div>
//                   )}
//                   {!generating && preview.length > 0 && (
//                     <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
//                       {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
//                     </span>
//                   )}
//                   {uploadErr && (
//                     <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
//                   )}
//                 </div>
//               </>
//             )}

//             {/* Video grid */}
//             <div ref={gridRef}>
//               {liveJob && (
//                 <VideoGrid
//                   job={liveJob}
//                   role={role}
//                   rejected={rejected}
//                   onReject={handleReject}
//                   onRerun={() => refetchJob()}
//                 />
//               )}
//             </div>
//           </>
//         )}

//         {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
//         {tab === 'youtube' && (
//           <>
//             <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
//               YouTube Queue
//             </SectionLabel>
//             <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
//               Approve a video card on the Generate tab to add it here.
//             </p>
//             <YouTubeQueue role={role} />
//           </>
//         )}

//         {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
//         {tab === 'data' && (
//           <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
//             {hasPermission(role, 'view_jobs') && <JobsPanel />}
//             {hasPermission(role, 'view_metrics') && <MetricsPanel />}
//             {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
//               <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
//             )}
//           </div>
//         )}
//       </main>
//     </div>
//   )
// }





























// // src/app/generate/page.tsx
// 'use client'
// import { useState, useEffect, useRef, useCallback } from 'react'
// import { useSession } from 'next-auth/react'
// import { useRouter } from 'next/navigation'
// import useSWR from 'swr'
// import { read, utils } from 'xlsx'

// import { Navbar }       from '@/components/Navbar'
// import { UploadZone, SectionLabel } from '@/components/UploadZone'
// import { PreviewTable } from '@/components/PreviewTable'
// import { VideoGrid }    from '@/components/VideoGrid'
// import { JobsPanel }    from '@/components/JobsPanel'
// import { MetricsPanel } from '@/components/MetricsPanel'
// import { YouTubeQueue } from '@/components/YouTubeQueue'
// import { Tooltip }      from '@/components/Tooltip'

// import { checkHealth, uploadFile, fetchJob } from '@/lib/api'
// import { hasPermission } from '@/lib/permissions'
// import type { Role } from '@/types'
// import type { Job, PreviewRow } from '@/types'

// // ── Sample xlsx generation (client-side) ────────────────────────────────────
// // Two separate sample files — one per mode — with appropriate columns and notes.

// async function downloadSampleFull() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   const rows = [
//     ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
//     [
//       'NARRATOR: warm, Indian-accented female voice, calm and confident, mid-30s professional tone'
//       + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops open.'
//       + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon-lit desks, large windows, daytime.'
//       + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level, slow push-in.'
//       + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.'
//       + 'Indian Accent Narration: "The future belongs to creators, not just users."'
//       + 'Students at glowing desks building chatbots and AI artwork, collaborative energy.'
//       + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."'
//       + 'Fast montage: AI artwork on screen, chatbot on phone, student designing a website.'
//       + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."'
//       + 'Confident student presenting AI project, classmates applauding, scene holds still.'
//       + 'Indian Accent Narration: "Start your AI journey today."',
//       32, '9:16', 'AUTO', 1,
//     ],
//     [
//       'NARRATOR: calm professional Indian male voice'
//       + 'SCENE ANCHOR: Corporate boardroom, floor-to-ceiling glass, city skyline, evening light.'
//       + 'CAMERA ANCHOR: Medium wide, eye level, slow push-in.'
//       + 'Professionals reviewing AI dashboards on laptops, confident expressions.'
//       + 'Narration: "What if your whole organisation could think smarter?"'
//       + 'Team nodding, collaborative energy, AI analytics glowing on screens.'
//       + 'Narration: "AI training for every leader, every team."'
//       + 'Team smiling, city skyline behind them, scene holds still.'
//       + 'Narration: "Build the future with your people."',
//       24, '16:9', 'AUTO', 2,
//     ],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 80 }, { wch: 10 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
//   x.book_append_sheet(wb, ws, 'prompts')
//   writeFile(wb, 'veo_full_length_sample.xlsx')
// }

// async function downloadSampleShortSpan() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   // Each row = one clip. No duration column — set from UI slider.
//   const rows = [
//     ['prompt', 'aspect_ratio'],
//     ['Wide shot of a school corridor, students walking purposefully, morning light, warm and vibrant atmosphere.', '9:16'],
//     ['Close-up of student hands typing on a glowing laptop, colourful code on screen, focused expression, shallow depth of field.', '9:16'],
//     ['Medium shot of a student looking at their screen with a delighted and surprised expression, soft smile, warm classroom light.', '9:16'],
//     ['Close-up of a phone showing a chatbot conversation interface labelled "AI Assistant", finger scrolling, clean UI.', '9:16'],
//     ['Three students gathered around a laptop pointing excitedly, laughing, creative energy, futuristic classroom background.', '9:16'],
//     ['Wide shot of a student standing confidently in front of a large screen showing "AI Innovators Program", smiling at camera, scene holds still.', '9:16'],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 90 }, { wch: 14 }]
//   x.book_append_sheet(wb, ws, 'clips')
//   // Reference sheet explaining the format
//   const ref = x.aoa_to_sheet([
//     ['SHORT SPAN CLIPS — Format Guide'],
//     [''],
//     ['Each row = one clip', 'No decomposition — you control every clip directly'],
//     ['prompt', 'Scene description for this specific clip. Precise visuals. No narration lines.'],
//     ['aspect_ratio', 'Reference only — 9:16, 16:9, 1:1. Set globally in veo.env.'],
//     ['duration', 'NOT USED — clip duration set from the UI slider (2–8s per clip).'],
//     ['task_type / priority', 'NOT USED — all rows are processed sequentially.'],
//     [''],
//     ['Clip chaining', 'Last frame of each clip anchors the next via img2vid.'],
//     ['Total video', 'Rows × clip duration. E.g. 6 rows × 2s = 12s final video.'],
//     ['No text / No speech', 'Set in UI — guardrail injected into all prompts automatically.'],
//   ])
//   ref['!cols'] = [{ wch: 28 }, { wch: 70 }]
//   x.book_append_sheet(wb, ref, 'reference')
//   writeFile(wb, 'veo_short_span_sample.xlsx')
// }
// // ── Parse Excel to preview rows ──────────────────────────────────────────────
// function parseExcel(file: File): Promise<PreviewRow[]> {
//   return new Promise((resolve, reject) => {
//     const reader = new FileReader()
//     reader.onload = e => {
//       try {
//         const data   = e.target?.result
//         const wb     = read(data, { type: 'array' })
//         const ws     = wb.Sheets[wb.SheetNames[0]]
//         const raw    = utils.sheet_to_json(ws, { defval: '' }) as Record<string, unknown>[]
//         // Normalise column names
//         const rows: PreviewRow[] = raw
//           .map(r => {
//             const lower: Record<string, unknown> = {}
//             for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
//             const dur = parseFloat(
//               String(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
//             )
//             return {
//               prompt:       String(lower['prompt'] ?? '').trim(),
//               duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
//               aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
//               task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
//               priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
//             }
//           })
//           .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
//         resolve(rows)
//       } catch (err) {
//         reject(err)
//       }
//     }
//     reader.onerror = reject
//     reader.readAsArrayBuffer(file)
//   })
// }

// type Tab = 'generate' | 'youtube' | 'data'

// // ── Page ─────────────────────────────────────────────────────────────────────
// // Local helper — avoids the `as const` readonly type conflict on setter functions
// function CheckboxToggle({
//   label, checked, onChange, tooltip,
// }: {
//   label:    string
//   checked:  boolean
//   onChange: (v: boolean) => void
//   tooltip:  string
// }) {
//   return (
//     <label style={{ display: 'flex', alignItems: 'center', gap: 8,
//       cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
//       <input
//         type="checkbox"
//         checked={checked}
//         onChange={e => onChange(e.target.checked)}
//         style={{ width: 15, height: 15, cursor: 'pointer', accentColor: 'var(--text)' }}
//       />
//       {label}
//       <Tooltip text={tooltip} />
//     </label>
//   )
// }

// export default function GeneratePage() {
//   const { data: session, status } = useSession()
//   const router = useRouter()
//   const role   = (session?.user?.role ?? 'viewer') as Role

//   // Redirect unauthenticated
//   useEffect(() => {
//     if (status === 'unauthenticated') router.push('/login')
//   }, [status, router])

//   const [tab, setTab]             = useState<Tab>('generate')
//   const [apiOk, setApiOk]         = useState<boolean | null>(null)
//   const [file, setFile]           = useState<File | null>(null)
//   const [preview, setPreview]     = useState<PreviewRow[]>([])
//   const [parseErr, setParseErr]   = useState('')
//   const [generating, setGenerating] = useState(false)
//   const [uploadErr, setUploadErr]   = useState('')

//   // Mode / feature toggles — placed before upload so user sets them first
//   const [mode, setMode]               = useState<'full' | 'short_span' | 'short_span_image'>('full')
//   const [shortSpanType, setShortSpanType] = useState<'video' | 'image'>('video')
//   const [clipDuration, setClipDuration]   = useState<number>(2)
//   const [holdDuration, setHoldDuration]   = useState<number>(5)
//   const [noText, setNoText]           = useState(false)
//   const [noSpeech, setNoSpeech]       = useState(false)

//   // Active job state
//   const [activeJobId, setActiveJobId]     = useState<string | null>(null)
//   const [lastJobId, setLastJobId]         = useState<string | null>(null)
//   const [rejected, setRejected]           = useState<Set<string>>(new Set())

//   // Polling
//   const displayJobId = activeJobId ?? lastJobId
//   const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
//     displayJobId ? `job-${displayJobId}` : null,
//     () => fetchJob(displayJobId!),
//     {
//       refreshInterval: activeJobId ? 4000 : 0,
//       onSuccess(job) {
//         if (!['processing', 'pending'].includes(job.status)) {
//           setLastJobId(job.job_id)
//           setActiveJobId(null)
//           setGenerating(false)
//           // Final refetch after a short delay ensures all prompt results are
//           // included — the job may flip to "completed" slightly before the
//           // last result is written into the jobs dict.
//           setTimeout(() => refetchJob(), 1500)
//         }
//       },
//     },
//   )

//   // Video grid anchor ref for smooth scroll on generation start
//   const gridRef = useRef<HTMLDivElement>(null)
//   useEffect(() => {
//     if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
//   }, [activeJobId])

//   // API health check on mount
//   useEffect(() => {
//     checkHealth().then(ok => setApiOk(ok))
//   }, [])

//   async function handleFile(f: File) {
//     setFile(f)
//     setParseErr('')
//     setPreview([])
//     try {
//       const rows = await parseExcel(f)
//       setPreview(rows)
//     } catch (err: unknown) {
//       setParseErr(`Could not parse file: ${err instanceof Error ? err.message : String(err)}`)
//     }
//   }

//   async function handleGenerate() {
//     if (!file || generating) return
//     setGenerating(true)
//     setUploadErr('')
//     setRejected(new Set())

//     try {
//       // Derive actual API mode from toggles
//       const apiMode = mode === 'short_span'
//         ? (shortSpanType === 'image' ? 'short_span_image' : 'short_span')
//         : 'full'

//       const result = await uploadFile(file, {
//         mode:         apiMode,
//         clipDuration,
//         holdDuration,
//         noText,
//         noSpeech,
//       })
//       setActiveJobId(result.job_id)
//     } catch (err: unknown) {
//       setUploadErr(`Upload failed: ${err instanceof Error ? err.message : String(err)}`)
//       setGenerating(false)
//     }
//   }

//   function handleReject(jobId: string, index: number) {
//     setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
//   }

//   const totalClips = preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
//   const totalDur   = preview.reduce((a, r) => a + (r.duration || 8), 0)

//   if (status === 'loading') return null

//   return (
//     <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
//       <Navbar />

//       {/* Tab bar */}
//       <div
//         style={{
//           borderBottom: '1px solid var(--border)',
//           padding: '0 2rem',
//           display: 'flex',
//           gap: 0,
//         }}
//       >
//         {([
//           ['generate', 'Generate'],
//           ['youtube',  'YouTube Queue'],
//           ['data',     'Jobs & Metrics'],
//         ] as [Tab, string][]).map(([id, label]) => (
//           <button
//             key={id}
//             onClick={() => setTab(id)}
//             style={{
//               fontSize: 13.5,
//               fontWeight: 500,
//               padding: '10px 16px',
//               background: 'none',
//               border: 'none',
//               borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
//               color: tab === id ? 'var(--text)' : 'var(--text2)',
//               cursor: 'pointer',
//               fontFamily: 'inherit',
//               transition: 'color .15s',
//             }}
//           >
//             {label}
//           </button>
//         ))}
//       </div>

//       {/* Content */}
//       <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

//         {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
//         {tab === 'generate' && (
//           <>
//             {/* API status */}
//             {apiOk === false && (
//               <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
//                 ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
//               </div>
//             )}

//             {/* ── Mode & options — set BEFORE uploading ── */}
//             <div style={{
//               background: 'var(--surface)',
//               border: '1px solid var(--border2)',
//               borderRadius: 'var(--radius-lg)',
//               padding: '1.25rem 1.5rem',
//               marginBottom: '1.5rem',
//               display: 'flex',
//               flexDirection: 'column',
//               gap: '1rem',
//             }}>
//               {/* Mode toggle */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                 <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                   Generation mode
//                 </span>
//                 <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                   border: '1px solid var(--border)' }}>
//                   {(['full', 'short_span'] as const).map(m => (
//                     <button key={m} onClick={() => setMode(m)} style={{
//                       padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                       background: mode === m ? 'var(--text)' : 'none',
//                       color: mode === m ? 'var(--bg)' : 'var(--text2)',
//                       border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                     }}>
//                       {m === 'full' ? 'Full Length Videos' : 'Short Span Clips'}
//                     </button>
//                   ))}
//                 </div>
//                 <Tooltip text={mode === 'full'
//                   ? 'Full pipeline: decomposition, multi-clip generation, img2vid chaining, stitching. Each Excel row = one full ad.'
//                   : 'Each Excel row = one discrete clip sent directly to Veo. No decomposition — you control each clip. Clips are chained and stitched into one video.'
//                 } />
//               </div>

//               {/* Short Span sub-toggle: Videos | Images */}
//               {mode === 'short_span' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip type
//                   </span>
//                   <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                     border: '1px solid var(--border)' }}>
//                     {(['video', 'image'] as const).map(t => (
//                       <button key={t} onClick={() => setShortSpanType(t)} style={{
//                         padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                         background: shortSpanType === t ? 'var(--text)' : 'none',
//                         color: shortSpanType === t ? 'var(--bg)' : 'var(--text2)',
//                         border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {t === 'video' ? '▶  Short Videos' : '🖼  Static Images'}
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text={shortSpanType === 'video'
//                     ? 'Each row generates a short Veo video clip (2–8s). Clips are chained via img2vid and stitched.'
//                     : 'Each row generates a static image via Google Imagen. Images are animated with Ken Burns effect and crossfaded into one video. Silent output.'
//                   } />
//                 </div>
//               )}

//               {/* Clip duration — short_span video only */}
//               {mode === 'short_span' && shortSpanType === 'video' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 3, 4, 5, 6, 8].map(d => (
//                       <button key={d} onClick={() => setClipDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: clipDuration === d ? 'var(--text)' : 'none',
//                         color: clipDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="Duration per clip sent to Veo (2–8 seconds). Total video = number of Excel rows × clip duration." />
//                 </div>
//               )}

//               {/* Hold duration — short_span image only */}
//               {mode === 'short_span' && shortSpanType === 'image' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Hold duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 5].map(d => (
//                       <button key={d} onClick={() => setHoldDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: holdDuration === d ? 'var(--text)' : 'none',
//                         color: holdDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="How long each image is held before crossfading to the next. Ken Burns animation plays during the hold. 2s for fast-paced, 5s for considered viewing." />
//                 </div>
//               )}

//               {/* No text / No speech */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
//                 <CheckboxToggle
//                   label="No text overlay"
//                   checked={noText}
//                   onChange={setNoText}
//                   tooltip="Injects a guardrail instructing Veo to not render any text, captions, titles, subtitles, or watermarks in the video frame."
//                 />
//                 {/* No speech not applicable to static images */}
//                 {!(mode === 'short_span' && shortSpanType === 'image') && (
//                   <CheckboxToggle
//                     label="No speech / narration"
//                     checked={noSpeech}
//                     onChange={setNoSpeech}
//                     tooltip="Characters will not speak or lip-sync — narration plays as a voiceover in the background. Natural scene movement is preserved. Use when you want the narrator speaking over visuals without character dialogue."
//                   />
//                 )}
//               </div>
//             </div>

//             {/* Upload section */}
//             <div style={{ marginBottom: '1.75rem' }}>
//               <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
//                 <SectionLabel tooltip={mode === 'short_span'
//                   ? 'Short Span: each row = one clip. No decomposition. Clip duration is set from the toggle above.'
//                   : 'Full Length: each row = one full ad. The platform decomposes multi-clip ads automatically.'
//                 }>
//                   Upload prompts
//                 </SectionLabel>
//                 <button
//                   onClick={() => mode === 'short_span' ? downloadSampleShortSpan() : downloadSampleFull()}
//                   style={{
//                     fontSize: 12.5,
//                     fontWeight: 500,
//                     padding: '6px 14px',
//                     borderRadius: 'var(--pill)',
//                     border: '1px solid var(--border)',
//                     background: 'none',
//                     color: 'var(--text2)',
//                     cursor: 'pointer',
//                     fontFamily: 'inherit',
//                   }}
//                 >
//                   ↓ Sample Excel ({mode === 'short_span' ? 'Short Span' : 'Full Length'})
//                 </button>
//               </div>
//               <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
//                 {mode === 'short_span'
//                   ? 'One row per clip — prompt column only. Aspect ratio optional. Duration and task type are ignored.'
//                   : 'Columns: prompt, duration, aspect_ratio, task_type, priority.'}
//               </p>
//               <UploadZone onFile={handleFile} disabled={generating} />
//               {parseErr && (
//                 <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
//               )}
//             </div>

//             {/* Preview table */}
//             {preview.length > 0 && (
//               <>
//                 <PreviewTable rows={preview} />

//                 {/* Generate CTA */}
//                 <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
//                   {hasPermission(role, 'generate') ? (
//                     <button
//                       onClick={handleGenerate}
//                       disabled={generating || !file}
//                       style={{
//                         background: 'var(--text)',
//                         color: 'var(--bg)',
//                         border: 'none',
//                         borderRadius: 'var(--pill)',
//                         padding: '10px 28px',
//                         fontSize: 15,
//                         fontWeight: 600,
//                         cursor: generating ? 'not-allowed' : 'pointer',
//                         opacity: generating ? 0.45 : 1,
//                         fontFamily: 'inherit',
//                         transition: 'opacity .15s',
//                         display: 'flex',
//                         alignItems: 'center',
//                         gap: 8,
//                       }}
//                     >
//                       {generating
//                         ? 'Generating…'
//                         : mode === 'short_span' && shortSpanType === 'image'
//                         ? `🖼  Generate  ·  ${preview.length} image${preview.length !== 1 ? 's' : ''} · ${preview.length * holdDuration}s total`
//                         : mode === 'short_span'
//                         ? `▶  Generate  ·  ${preview.length} clip${preview.length !== 1 ? 's' : ''} · ${preview.length * clipDuration}s total`
//                         : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
//                     </button>
//                   ) : (
//                     <div className="alert alert-warn" style={{ margin: 0 }}>
//                       ⚠️  Your role cannot generate videos.
//                     </div>
//                   )}
//                   {!generating && preview.length > 0 && (
//                     <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
//                       {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
//                     </span>
//                   )}
//                   {uploadErr && (
//                     <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
//                   )}
//                 </div>
//               </>
//             )}

//             {/* Video grid */}
//             <div ref={gridRef}>
//               {liveJob && (
//                 <VideoGrid
//                   job={liveJob}
//                   role={role}
//                   rejected={rejected}
//                   onReject={handleReject}
//                   onRerun={() => refetchJob()}
//                 />
//               )}
//             </div>
//           </>
//         )}

//         {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
//         {tab === 'youtube' && (
//           <>
//             <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
//               YouTube Queue
//             </SectionLabel>
//             <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
//               Approve a video card on the Generate tab to add it here.
//             </p>
//             <YouTubeQueue role={role} />
//           </>
//         )}

//         {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
//         {tab === 'data' && (
//           <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
//             {hasPermission(role, 'view_jobs') && <JobsPanel />}
//             {hasPermission(role, 'view_metrics') && <MetricsPanel />}
//             {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
//               <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
//             )}
//           </div>
//         )}
//       </main>
//     </div>
//   )
// }























// // src/app/generate/page.tsx
// 'use client'
// import { useState, useEffect, useRef, useCallback } from 'react'
// import { useSession } from 'next-auth/react'
// import { useRouter } from 'next/navigation'
// import useSWR from 'swr'
// import { read, utils } from 'xlsx'

// import { Navbar }       from '@/components/Navbar'
// import { UploadZone, SectionLabel } from '@/components/UploadZone'
// import { PreviewTable } from '@/components/PreviewTable'
// import { VideoGrid }    from '@/components/VideoGrid'
// import { JobsPanel }    from '@/components/JobsPanel'
// import { MetricsPanel } from '@/components/MetricsPanel'
// import { YouTubeQueue } from '@/components/YouTubeQueue'
// import { Tooltip }      from '@/components/Tooltip'

// import { checkHealth, uploadFile, fetchJob } from '@/lib/api'
// import { hasPermission } from '@/lib/permissions'
// import type { Role } from '@/types'
// import type { Job, PreviewRow } from '@/types'

// // ── Sample xlsx generation (client-side) ────────────────────────────────────
// // Two separate sample files — one per mode — with appropriate columns and notes.

// async function downloadSampleFull() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   const rows = [
//     ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
//     [
//       'NARRATOR: warm, Indian-accented female voice, calm and confident, mid-30s professional tone'
//       + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops open.'
//       + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon-lit desks, large windows, daytime.'
//       + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level, slow push-in.'
//       + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.'
//       + 'Indian Accent Narration: "The future belongs to creators, not just users."'
//       + 'Students at glowing desks building chatbots and AI artwork, collaborative energy.'
//       + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."'
//       + 'Fast montage: AI artwork on screen, chatbot on phone, student designing a website.'
//       + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."'
//       + 'Confident student presenting AI project, classmates applauding, scene holds still.'
//       + 'Indian Accent Narration: "Start your AI journey today."',
//       32, '9:16', 'AUTO', 1,
//     ],
//     [
//       'NARRATOR: calm professional Indian male voice'
//       + 'SCENE ANCHOR: Corporate boardroom, floor-to-ceiling glass, city skyline, evening light.'
//       + 'CAMERA ANCHOR: Medium wide, eye level, slow push-in.'
//       + 'Professionals reviewing AI dashboards on laptops, confident expressions.'
//       + 'Narration: "What if your whole organisation could think smarter?"'
//       + 'Team nodding, collaborative energy, AI analytics glowing on screens.'
//       + 'Narration: "AI training for every leader, every team."'
//       + 'Team smiling, city skyline behind them, scene holds still.'
//       + 'Narration: "Build the future with your people."',
//       24, '16:9', 'AUTO', 2,
//     ],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 80 }, { wch: 10 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
//   x.book_append_sheet(wb, ws, 'prompts')
//   writeFile(wb, 'veo_full_length_sample.xlsx')
// }

// async function downloadSampleShortSpan() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   // Each row = one clip. No duration column — set from UI slider.
//   const rows = [
//     ['prompt', 'aspect_ratio'],
//     ['Wide shot of a school corridor, students walking purposefully, morning light, warm and vibrant atmosphere.', '9:16'],
//     ['Close-up of student hands typing on a glowing laptop, colourful code on screen, focused expression, shallow depth of field.', '9:16'],
//     ['Medium shot of a student looking at their screen with a delighted and surprised expression, soft smile, warm classroom light.', '9:16'],
//     ['Close-up of a phone showing a chatbot conversation interface labelled "AI Assistant", finger scrolling, clean UI.', '9:16'],
//     ['Three students gathered around a laptop pointing excitedly, laughing, creative energy, futuristic classroom background.', '9:16'],
//     ['Wide shot of a student standing confidently in front of a large screen showing "AI Innovators Program", smiling at camera, scene holds still.', '9:16'],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 90 }, { wch: 14 }]
//   x.book_append_sheet(wb, ws, 'clips')
//   // Reference sheet explaining the format
//   const ref = x.aoa_to_sheet([
//     ['SHORT SPAN CLIPS — Format Guide'],
//     [''],
//     ['Each row = one clip', 'No decomposition — you control every clip directly'],
//     ['prompt', 'Scene description for this specific clip. Precise visuals. No narration lines.'],
//     ['aspect_ratio', 'Reference only — 9:16, 16:9, 1:1. Set globally in veo.env.'],
//     ['duration', 'NOT USED — clip duration set from the UI slider (2–8s per clip).'],
//     ['task_type / priority', 'NOT USED — all rows are processed sequentially.'],
//     [''],
//     ['Clip chaining', 'Last frame of each clip anchors the next via img2vid.'],
//     ['Total video', 'Rows × clip duration. E.g. 6 rows × 2s = 12s final video.'],
//     ['No text / No speech', 'Set in UI — guardrail injected into all prompts automatically.'],
//   ])
//   ref['!cols'] = [{ wch: 28 }, { wch: 70 }]
//   x.book_append_sheet(wb, ref, 'reference')
//   writeFile(wb, 'veo_short_span_sample.xlsx')
// }
// // ── Parse Excel to preview rows ──────────────────────────────────────────────
// function parseExcel(file: File): Promise<PreviewRow[]> {
//   return new Promise((resolve, reject) => {
//     const reader = new FileReader()
//     reader.onload = e => {
//       try {
//         const data   = e.target?.result
//         const wb     = read(data, { type: 'array' })
//         const ws     = wb.Sheets[wb.SheetNames[0]]
//         const raw    = utils.sheet_to_json(ws, { defval: '' }) as Record<string, unknown>[]
//         // Normalise column names
//         const rows: PreviewRow[] = raw
//           .map(r => {
//             const lower: Record<string, unknown> = {}
//             for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
//             const dur = parseFloat(
//               String(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
//             )
//             return {
//               prompt:       String(lower['prompt'] ?? '').trim(),
//               duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
//               aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
//               task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
//               priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
//             }
//           })
//           .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
//         resolve(rows)
//       } catch (err) {
//         reject(err)
//       }
//     }
//     reader.onerror = reject
//     reader.readAsArrayBuffer(file)
//   })
// }

// type Tab = 'generate' | 'youtube' | 'data'

// // ── Page ─────────────────────────────────────────────────────────────────────
// // Local helper — avoids the `as const` readonly type conflict on setter functions
// function CheckboxToggle({
//   label, checked, onChange, tooltip,
// }: {
//   label:    string
//   checked:  boolean
//   onChange: (v: boolean) => void
//   tooltip:  string
// }) {
//   return (
//     <label style={{ display: 'flex', alignItems: 'center', gap: 8,
//       cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
//       <input
//         type="checkbox"
//         checked={checked}
//         onChange={e => onChange(e.target.checked)}
//         style={{ width: 15, height: 15, cursor: 'pointer', accentColor: 'var(--text)' }}
//       />
//       {label}
//       <Tooltip text={tooltip} />
//     </label>
//   )
// }

// export default function GeneratePage() {
//   const { data: session, status } = useSession()
//   const router = useRouter()
//   const role   = (session?.user?.role ?? 'viewer') as Role

//   // Redirect unauthenticated
//   useEffect(() => {
//     if (status === 'unauthenticated') router.push('/login')
//   }, [status, router])

//   const [tab, setTab]             = useState<Tab>('generate')
//   const [apiOk, setApiOk]         = useState<boolean | null>(null)
//   const [file, setFile]           = useState<File | null>(null)
//   const [preview, setPreview]     = useState<PreviewRow[]>([])
//   const [parseErr, setParseErr]   = useState('')
//   const [generating, setGenerating] = useState(false)
//   const [uploadErr, setUploadErr]   = useState('')

//   // Mode / feature toggles — placed before upload so user sets them first
//   const [mode, setMode]               = useState<'full' | 'short_span' | 'short_span_image'>('full')
//   const [shortSpanType, setShortSpanType] = useState<'video' | 'image'>('video')
//   const [clipDuration, setClipDuration]   = useState<number>(2)
//   const [holdDuration, setHoldDuration]   = useState<number>(5)
//   const [noText, setNoText]           = useState(false)
//   const [noSpeech, setNoSpeech]       = useState(false)

//   // Active job state
//   const [activeJobId, setActiveJobId]     = useState<string | null>(null)
//   const [lastJobId, setLastJobId]         = useState<string | null>(null)
//   const [rejected, setRejected]           = useState<Set<string>>(new Set())

//   // Polling
//   const displayJobId = activeJobId ?? lastJobId
//   const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
//     displayJobId ? `job-${displayJobId}` : null,
//     () => fetchJob(displayJobId!),
//     {
//       refreshInterval: activeJobId ? 4000 : 0,
//       onSuccess(job) {
//         if (!['processing', 'pending'].includes(job.status)) {
//           setLastJobId(job.job_id)
//           setActiveJobId(null)
//           setGenerating(false)
//           // Final refetch after a short delay ensures all prompt results are
//           // included — the job may flip to "completed" slightly before the
//           // last result is written into the jobs dict.
//           setTimeout(() => refetchJob(), 1500)
//         }
//       },
//     },
//   )

//   // Video grid anchor ref for smooth scroll on generation start
//   const gridRef = useRef<HTMLDivElement>(null)
//   useEffect(() => {
//     if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
//   }, [activeJobId])

//   // API health check on mount
//   useEffect(() => {
//     checkHealth().then(ok => setApiOk(ok))
//   }, [])

//   async function handleFile(f: File) {
//     setFile(f)
//     setParseErr('')
//     setPreview([])
//     try {
//       const rows = await parseExcel(f)
//       setPreview(rows)
//     } catch (err: unknown) {
//       setParseErr(`Could not parse file: ${err instanceof Error ? err.message : String(err)}`)
//     }
//   }

//   async function handleGenerate() {
//     if (!file || generating) return
//     setGenerating(true)
//     setUploadErr('')
//     setRejected(new Set())

//     try {
//       // Derive actual API mode from toggles
//       const apiMode = mode === 'short_span'
//         ? (shortSpanType === 'image' ? 'short_span_image' : 'short_span')
//         : 'full'

//       const result = await uploadFile(file, {
//         mode:         apiMode,
//         clipDuration,
//         holdDuration,
//         noText,
//         noSpeech,
//       })
//       setActiveJobId(result.job_id)
//     } catch (err: unknown) {
//       setUploadErr(`Upload failed: ${err instanceof Error ? err.message : String(err)}`)
//       setGenerating(false)
//     }
//   }

//   function handleReject(jobId: string, index: number) {
//     setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
//   }

//   const totalClips = preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
//   const totalDur   = preview.reduce((a, r) => a + (r.duration || 8), 0)

//   if (status === 'loading') return null

//   return (
//     <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
//       <Navbar />

//       {/* Tab bar */}
//       <div
//         style={{
//           borderBottom: '1px solid var(--border)',
//           padding: '0 2rem',
//           display: 'flex',
//           gap: 0,
//         }}
//       >
//         {([
//           ['generate', 'Generate'],
//           ['youtube',  'YouTube Queue'],
//           ['data',     'Jobs & Metrics'],
//         ] as [Tab, string][]).map(([id, label]) => (
//           <button
//             key={id}
//             onClick={() => setTab(id)}
//             style={{
//               fontSize: 13.5,
//               fontWeight: 500,
//               padding: '10px 16px',
//               background: 'none',
//               border: 'none',
//               borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
//               color: tab === id ? 'var(--text)' : 'var(--text2)',
//               cursor: 'pointer',
//               fontFamily: 'inherit',
//               transition: 'color .15s',
//             }}
//           >
//             {label}
//           </button>
//         ))}
//       </div>

//       {/* Content */}
//       <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

//         {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
//         {tab === 'generate' && (
//           <>
//             {/* API status */}
//             {apiOk === false && (
//               <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
//                 ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
//               </div>
//             )}

//             {/* ── Mode & options — set BEFORE uploading ── */}
//             <div style={{
//               background: 'var(--surface)',
//               border: '1px solid var(--border2)',
//               borderRadius: 'var(--radius-lg)',
//               padding: '1.25rem 1.5rem',
//               marginBottom: '1.5rem',
//               display: 'flex',
//               flexDirection: 'column',
//               gap: '1rem',
//             }}>
//               {/* Mode toggle */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                 <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                   Generation mode
//                 </span>
//                 <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                   border: '1px solid var(--border)' }}>
//                   {(['full', 'short_span'] as const).map(m => (
//                     <button key={m} onClick={() => setMode(m)} style={{
//                       padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                       background: mode === m ? 'var(--text)' : 'none',
//                       color: mode === m ? 'var(--bg)' : 'var(--text2)',
//                       border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                     }}>
//                       {m === 'full' ? 'Full Length Videos' : 'Short Span Clips'}
//                     </button>
//                   ))}
//                 </div>
//                 <Tooltip text={mode === 'full'
//                   ? 'Full pipeline: decomposition, multi-clip generation, img2vid chaining, stitching. Each Excel row = one full ad.'
//                   : 'Each Excel row = one discrete clip sent directly to Veo. No decomposition — you control each clip. Clips are chained and stitched into one video.'
//                 } />
//               </div>

//               {/* Short Span sub-toggle: Videos | Images */}
//               {mode === 'short_span' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip type
//                   </span>
//                   <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                     border: '1px solid var(--border)' }}>
//                     {(['video', 'image'] as const).map(t => (
//                       <button key={t} onClick={() => setShortSpanType(t)} style={{
//                         padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                         background: shortSpanType === t ? 'var(--text)' : 'none',
//                         color: shortSpanType === t ? 'var(--bg)' : 'var(--text2)',
//                         border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {t === 'video' ? '▶  Short Videos' : '🖼  Static Images'}
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text={shortSpanType === 'video'
//                     ? 'Each row generates a short Veo video clip (2–8s). Clips are chained via img2vid and stitched.'
//                     : 'Each row generates a static image via Google Imagen. Images are animated with Ken Burns effect and crossfaded into one video. Silent output.'
//                   } />
//                 </div>
//               )}

//               {/* Clip duration — short_span video only */}
//               {mode === 'short_span' && shortSpanType === 'video' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 3, 4, 5, 6, 8].map(d => (
//                       <button key={d} onClick={() => setClipDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: clipDuration === d ? 'var(--text)' : 'none',
//                         color: clipDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="Duration per clip sent to Veo (2–8 seconds). Total video = number of Excel rows × clip duration." />
//                 </div>
//               )}

//               {/* Hold duration — short_span image only */}
//               {mode === 'short_span' && shortSpanType === 'image' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Hold duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 5].map(d => (
//                       <button key={d} onClick={() => setHoldDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: holdDuration === d ? 'var(--text)' : 'none',
//                         color: holdDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="How long each image is held before crossfading to the next. Ken Burns animation plays during the hold. 2s for fast-paced, 5s for considered viewing." />
//                 </div>
//               )}

//               {/* No text / No speech */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
//                 <CheckboxToggle
//                   label="No text overlay"
//                   checked={noText}
//                   onChange={setNoText}
//                   tooltip="Injects a guardrail instructing Veo to not render any text, captions, titles, subtitles, or watermarks in the video frame."
//                 />
//                 {/* No speech not applicable to static images */}
//                 {!(mode === 'short_span' && shortSpanType === 'image') && (
//                   <CheckboxToggle
//                     label="No speech / narration"
//                     checked={noSpeech}
//                     onChange={setNoSpeech}
//                     tooltip="Characters will not speak or lip-sync — narration plays as a voiceover in the background. Natural scene movement is preserved. Use when you want the narrator speaking over visuals without character dialogue."
//                   />
//                 )}
//               </div>
//             </div>

//             {/* Upload section */}
//             <div style={{ marginBottom: '1.75rem' }}>
//               <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
//                 <SectionLabel tooltip={mode === 'short_span'
//                   ? 'Short Span: each row = one clip. No decomposition. Clip duration is set from the toggle above.'
//                   : 'Full Length: each row = one full ad. The platform decomposes multi-clip ads automatically.'
//                 }>
//                   Upload prompts
//                 </SectionLabel>
//                 <button
//                   onClick={() => mode === 'short_span' ? downloadSampleShortSpan() : downloadSampleFull()}
//                   style={{
//                     fontSize: 12.5,
//                     fontWeight: 500,
//                     padding: '6px 14px',
//                     borderRadius: 'var(--pill)',
//                     border: '1px solid var(--border)',
//                     background: 'none',
//                     color: 'var(--text2)',
//                     cursor: 'pointer',
//                     fontFamily: 'inherit',
//                   }}
//                 >
//                   ↓ Sample Excel ({mode === 'short_span' ? 'Short Span' : 'Full Length'})
//                 </button>
//               </div>
//               <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
//                 {mode === 'short_span'
//                   ? 'One row per clip — prompt column only. Aspect ratio optional. Duration and task type are ignored.'
//                   : 'Columns: prompt, duration, aspect_ratio, task_type, priority.'}
//               </p>
//               <UploadZone onFile={handleFile} disabled={generating} />
//               {parseErr && (
//                 <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
//               )}
//             </div>

//             {/* Preview table */}
//             {preview.length > 0 && (
//               <>
//                 <PreviewTable rows={preview} mode={mode === 'short_span' && shortSpanType === 'image' ? 'short_span_image' : mode === 'short_span' ? 'short_span' : 'full'} clipDuration={clipDuration} />

//                 {/* Generate CTA */}
//                 <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
//                   {hasPermission(role, 'generate') ? (
//                     <button
//                       onClick={handleGenerate}
//                       disabled={generating || !file}
//                       style={{
//                         background: 'var(--text)',
//                         color: 'var(--bg)',
//                         border: 'none',
//                         borderRadius: 'var(--pill)',
//                         padding: '10px 28px',
//                         fontSize: 15,
//                         fontWeight: 600,
//                         cursor: generating ? 'not-allowed' : 'pointer',
//                         opacity: generating ? 0.45 : 1,
//                         fontFamily: 'inherit',
//                         transition: 'opacity .15s',
//                         display: 'flex',
//                         alignItems: 'center',
//                         gap: 8,
//                       }}
//                     >
//                       {generating
//                         ? 'Generating…'
//                         : mode === 'short_span' && shortSpanType === 'image'
//                         ? `🖼  Generate  ·  ${preview.length} image${preview.length !== 1 ? 's' : ''} · ${preview.length * holdDuration}s total`
//                         : mode === 'short_span'
//                         ? `▶  Generate  ·  ${preview.length} clip${preview.length !== 1 ? 's' : ''} · ${preview.length * clipDuration}s total`
//                         : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
//                     </button>
//                   ) : (
//                     <div className="alert alert-warn" style={{ margin: 0 }}>
//                       ⚠️  Your role cannot generate videos.
//                     </div>
//                   )}
//                   {!generating && preview.length > 0 && (
//                     <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
//                       {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
//                     </span>
//                   )}
//                   {uploadErr && (
//                     <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
//                   )}
//                 </div>
//               </>
//             )}

//             {/* Video grid */}
//             <div ref={gridRef}>
//               {liveJob && (
//                 <VideoGrid
//                   job={liveJob}
//                   role={role}
//                   rejected={rejected}
//                   onReject={handleReject}
//                   onRerun={() => refetchJob()}
//                 />
//               )}
//             </div>
//           </>
//         )}

//         {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
//         {tab === 'youtube' && (
//           <>
//             <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
//               YouTube Queue
//             </SectionLabel>
//             <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
//               Approve a video card on the Generate tab to add it here.
//             </p>
//             <YouTubeQueue role={role} />
//           </>
//         )}

//         {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
//         {tab === 'data' && (
//           <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
//             {hasPermission(role, 'view_jobs') && <JobsPanel />}
//             {hasPermission(role, 'view_metrics') && <MetricsPanel />}
//             {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
//               <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
//             )}
//           </div>
//         )}
//       </main>
//     </div>
//   )
// }
































// // src/app/generate/page.tsx
// 'use client'
// import { useState, useEffect, useRef } from 'react'
// import { useSession } from 'next-auth/react'
// import { useRouter } from 'next/navigation'
// import useSWR from 'swr'
// import { read, utils } from 'xlsx'

// import { Navbar }       from '@/components/Navbar'
// import { UploadZone, SectionLabel } from '@/components/UploadZone'
// import { PreviewTable } from '@/components/PreviewTable'
// import { VideoGrid }    from '@/components/VideoGrid'
// import { JobsPanel }         from '@/components/JobsPanel'
// import { RefinementOverlay } from '@/components/RefinementOverlay'
// import { UsersPanel }   from '@/components/UsersPanel'
// import { MetricsPanel } from '@/components/MetricsPanel'
// import { YouTubeQueue } from '@/components/YouTubeQueue'
// import { Tooltip }      from '@/components/Tooltip'

// import { checkHealth, uploadFile, fetchJob, refinePrompts, approveJob, rejectJob } from '@/lib/api'
// import { hasPermission } from '@/lib/permissions'
// import type { Role, RefineResponse } from '@/types'
// import type { Job, PreviewRow } from '@/types'

// // ── Sample xlsx generation (client-side) ────────────────────────────────────
// // Two separate sample files — one per mode — with appropriate columns and notes.

// async function downloadSampleFull() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   const rows = [
//     ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
//     [
//       'NARRATOR: warm, Indian-accented female voice, calm and confident, mid-30s professional tone'
//       + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops open.'
//       + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon-lit desks, large windows, daytime.'
//       + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level, slow push-in.'
//       + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.'
//       + 'Indian Accent Narration: "The future belongs to creators, not just users."'
//       + 'Students at glowing desks building chatbots and AI artwork, collaborative energy.'
//       + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."'
//       + 'Fast montage: AI artwork on screen, chatbot on phone, student designing a website.'
//       + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."'
//       + 'Confident student presenting AI project, classmates applauding, scene holds still.'
//       + 'Indian Accent Narration: "Start your AI journey today."',
//       32, '9:16', 'AUTO', 1,
//     ],
//     [
//       'NARRATOR: calm professional Indian male voice'
//       + 'SCENE ANCHOR: Corporate boardroom, floor-to-ceiling glass, city skyline, evening light.'
//       + 'CAMERA ANCHOR: Medium wide, eye level, slow push-in.'
//       + 'Professionals reviewing AI dashboards on laptops, confident expressions.'
//       + 'Narration: "What if your whole organisation could think smarter?"'
//       + 'Team nodding, collaborative energy, AI analytics glowing on screens.'
//       + 'Narration: "AI training for every leader, every team."'
//       + 'Team smiling, city skyline behind them, scene holds still.'
//       + 'Narration: "Build the future with your people."',
//       24, '16:9', 'AUTO', 2,
//     ],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 80 }, { wch: 10 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
//   x.book_append_sheet(wb, ws, 'prompts')
//   writeFile(wb, 'veo_full_length_sample.xlsx')
// }

// async function downloadSampleShortSpan() {
//   const { utils: x, writeFile } = await import('xlsx')
//   const wb = x.book_new()
//   // Each row = one clip. No duration column — set from UI slider.
//   const rows = [
//     ['prompt', 'aspect_ratio'],
//     ['Wide shot of a school corridor, students walking purposefully, morning light, warm and vibrant atmosphere.', '9:16'],
//     ['Close-up of student hands typing on a glowing laptop, colourful code on screen, focused expression, shallow depth of field.', '9:16'],
//     ['Medium shot of a student looking at their screen with a delighted and surprised expression, soft smile, warm classroom light.', '9:16'],
//     ['Close-up of a phone showing a chatbot conversation interface labelled "AI Assistant", finger scrolling, clean UI.', '9:16'],
//     ['Three students gathered around a laptop pointing excitedly, laughing, creative energy, futuristic classroom background.', '9:16'],
//     ['Wide shot of a student standing confidently in front of a large screen showing "AI Innovators Program", smiling at camera, scene holds still.', '9:16'],
//   ]
//   const ws = x.aoa_to_sheet(rows)
//   ws['!cols'] = [{ wch: 90 }, { wch: 14 }]
//   x.book_append_sheet(wb, ws, 'clips')
//   // Reference sheet explaining the format
//   const ref = x.aoa_to_sheet([
//     ['SHORT SPAN CLIPS — Format Guide'],
//     [''],
//     ['Each row = one clip', 'No decomposition — you control every clip directly'],
//     ['prompt', 'Scene description for this specific clip. Precise visuals. No narration lines.'],
//     ['aspect_ratio', 'Reference only — 9:16, 16:9, 1:1. Set globally in veo.env.'],
//     ['duration', 'NOT USED — clip duration set from the UI slider (2–8s per clip).'],
//     ['task_type / priority', 'NOT USED — all rows are processed sequentially.'],
//     [''],
//     ['Clip chaining', 'Last frame of each clip anchors the next via img2vid.'],
//     ['Total video', 'Rows × clip duration. E.g. 6 rows × 2s = 12s final video.'],
//     ['No text / No speech', 'Set in UI — guardrail injected into all prompts automatically.'],
//   ])
//   ref['!cols'] = [{ wch: 28 }, { wch: 70 }]
//   x.book_append_sheet(wb, ref, 'reference')
//   writeFile(wb, 'veo_short_span_sample.xlsx')
// }
// // ── Parse Excel to preview rows ──────────────────────────────────────────────
// function parseExcel(file: File): Promise<PreviewRow[]> {
//   return new Promise((resolve, reject) => {
//     const reader = new FileReader()
//     reader.onload = e => {
//       try {
//         const data   = e.target?.result
//         const wb     = read(data, { type: 'array' })
//         const ws     = wb.Sheets[wb.SheetNames[0]]
//         const raw    = utils.sheet_to_json(ws, { defval: '' }) as Record<string, unknown>[]
//         // Normalise column names
//         const rows: PreviewRow[] = raw
//           .map(r => {
//             const lower: Record<string, unknown> = {}
//             for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
//             const dur = parseFloat(
//               String(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
//             )
//             return {
//               prompt:       String(lower['prompt'] ?? '').trim(),
//               duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
//               aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
//               task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
//               priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
//             }
//           })
//           .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
//         resolve(rows)
//       } catch (err) {
//         reject(err)
//       }
//     }
//     reader.onerror = reject
//     reader.readAsArrayBuffer(file)
//   })
// }

// type Tab = 'generate' | 'youtube' | 'data' | 'users'

// // ── Page ─────────────────────────────────────────────────────────────────────
// // Local helper — avoids the `as const` readonly type conflict on setter functions
// function CheckboxToggle({
//   label, checked, onChange, tooltip,
// }: {
//   label:    string
//   checked:  boolean
//   onChange: (v: boolean) => void
//   tooltip:  string
// }) {
//   return (
//     <label style={{ display: 'flex', alignItems: 'center', gap: 8,
//       cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
//       <input
//         type="checkbox"
//         checked={checked}
//         onChange={e => onChange(e.target.checked)}
//         style={{ width: 15, height: 15, cursor: 'pointer', accentColor: 'var(--text)' }}
//       />
//       {label}
//       <Tooltip text={tooltip} />
//     </label>
//   )
// }

// export default function GeneratePage() {
//   const { data: session, status } = useSession()
//   const router = useRouter()
//   const role   = (session?.user?.role ?? 'viewer') as Role

//   // Redirect unauthenticated
//   useEffect(() => {
//     if (status === 'unauthenticated') router.push('/login')
//   }, [status, router])

//   const [tab, setTab]             = useState<Tab>('generate')
//   const [apiOk, setApiOk]         = useState<boolean | null>(null)
//   const [file, setFile]           = useState<File | null>(null)
//   const [preview, setPreview]     = useState<PreviewRow[]>([])
//   const [parseErr, setParseErr]   = useState('')
//   const [generating, setGenerating] = useState(false)
//   const [uploadErr, setUploadErr]   = useState('')

//   // Mode / feature toggles — placed before upload so user sets them first
//   const [mode, setMode]               = useState<'full' | 'short_span' | 'short_span_image'>('full')

//   // ── Refinement flow ─────────────────────────────────────────────────────────
//   type FlowState = 'idle' | 'refining' | 'awaiting_approval' | 'generating'
//   const [flowState, setFlowState]       = useState<FlowState>('idle')
//   const [refineResult, setRefineResult] = useState<RefineResponse | null>(null)
//   const [refinerMode, setRefinerMode]   = useState<1 | 2>(1)
//   const [refineErr, setRefineErr]       = useState<string | null>(null)
//   const [shortSpanType, setShortSpanType] = useState<'video' | 'image'>('video')
//   const [clipDuration, setClipDuration]   = useState<number>(2)
//   const [holdDuration, setHoldDuration]   = useState<number>(5)
//   const [noText, setNoText]           = useState(false)
//   const [noSpeech, setNoSpeech]       = useState(false)

//   // Active job state
//   const [activeJobId, setActiveJobId]     = useState<string | null>(null)
//   const [lastJobId, setLastJobId]         = useState<string | null>(null)
//   const [rejected, setRejected]           = useState<Set<string>>(new Set())

//   // Polling
//   const displayJobId = activeJobId ?? lastJobId
//   const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
//     displayJobId ? `job-${displayJobId}` : null,
//     () => fetchJob(displayJobId!),
//     {
//       refreshInterval: activeJobId ? 4000 : 0,
//       onSuccess(job) {
//         if (!['processing', 'pending'].includes(job.status)) {
//           setLastJobId(job.job_id)
//           setActiveJobId(null)
//           setGenerating(false)
//           // Final refetch after a short delay ensures all prompt results are
//           // included — the job may flip to "completed" slightly before the
//           // last result is written into the jobs dict.
//           setTimeout(() => refetchJob(), 1500)
//         }
//       },
//     },
//   )

//   // Video grid anchor ref for smooth scroll on generation start
//   const gridRef = useRef<HTMLDivElement>(null)
//   useEffect(() => {
//     if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
//   }, [activeJobId])

//   // API health check on mount
//   useEffect(() => {
//     checkHealth().then(ok => setApiOk(ok))
//   }, [])

//   async function handleFile(f: File) {
//     setFile(f)
//     setParseErr('')
//     setPreview([])
//     try {
//       const rows = await parseExcel(f)
//       setPreview(rows)
//     } catch (err: unknown) {
//       setParseErr(`Could not parse file: ${err instanceof Error ? err.message : String(err)}`)
//     }
//   }

//   async function handleGenerate() {
//     // Redirect to two-step refinement flow
//     return handleRefineAndPreview()
//   }

//   async function handleRefineAndPreview() {
//     if (!file) return
//     setRefineErr(null)
//     setFlowState('refining')
//     setUploadErr('')
//     setRejected(new Set())

//     const apiMode = mode === 'short_span'
//       ? (shortSpanType === 'image' ? 'short_span_image' : 'short_span')
//       : 'full'

//     try {
//       const result = await refinePrompts(file, {
//         mode:         apiMode,
//         clipDuration,
//         holdDuration,
//         noText,
//         noSpeech,
//         refinerMode,
//       })
//       setRefineResult(result)
//       setFlowState('awaiting_approval')
//     } catch (err: unknown) {
//       setRefineErr(err instanceof Error ? err.message : String(err))
//       setFlowState('idle')
//     }
//   }

//   async function handleApprove(approvedRows: { rowIndex: number; finalPrompt: string }[]) {
//     if (!refineResult) return
//     setFlowState('generating')
//     setGenerating(true)
//     try {
//       const { jobId } = await approveJob(refineResult.jobId, approvedRows)
//       setActiveJobId(jobId)
//       setTab('generate')
//     } catch (err: unknown) {
//       setRefineErr(err instanceof Error ? err.message : String(err))
//       setFlowState('idle')
//       setGenerating(false)
//     }
//   }

//   async function handleRejectRefinement() {
//     if (refineResult) {
//       await rejectJob(refineResult.jobId).catch(() => {})
//     }
//     setRefineResult(null)
//     setFlowState('idle')
//   }

//   function handleReject(jobId: string, index: number) {
//     setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
//   }

//   const totalClips = preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
//   const totalDur   = preview.reduce((a, r) => a + (r.duration || 8), 0)

//   if (status === 'loading') return null

//   return (
//     <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
//       {flowState === 'awaiting_approval' && refineResult && (
//         <RefinementOverlay
//           jobId={refineResult.jobId}
//           rows={refineResult.rows}
//           refinerMode={refinerMode}
//           onApprove={handleApprove}
//           onReject={handleRejectRefinement}
//         />
//       )}
//       <Navbar />

//       {/* Tab bar */}
//       <div
//         style={{
//           borderBottom: '1px solid var(--border)',
//           padding: '0 2rem',
//           display: 'flex',
//           gap: 0,
//         }}
//       >
//         {([
//           ['generate', 'Generate'],
//           ['youtube',  'YouTube Queue'],
//           ['data',     'Jobs & Metrics'],
//           ...(hasPermission(role, 'view_jobs') ? [['users', 'Users']] as [Tab, string][] : []),
//         ] as [Tab, string][]).map(([id, label]) => (
//           <button
//             key={id}
//             onClick={() => setTab(id)}
//             style={{
//               fontSize: 13.5,
//               fontWeight: 500,
//               padding: '10px 16px',
//               background: 'none',
//               border: 'none',
//               borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
//               color: tab === id ? 'var(--text)' : 'var(--text2)',
//               cursor: 'pointer',
//               fontFamily: 'inherit',
//               transition: 'color .15s',
//             }}
//           >
//             {label}
//           </button>
//         ))}
//       </div>

//       {/* Content */}
//       <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

//         {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
//         {tab === 'generate' && (
//           <>
//             {/* API status */}
//             {apiOk === false && (
//               <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
//                 ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
//               </div>
//             )}

//             {/* ── Mode & options — set BEFORE uploading ── */}
//             <div style={{
//               background: 'var(--surface)',
//               border: '1px solid var(--border2)',
//               borderRadius: 'var(--radius-lg)',
//               padding: '1.25rem 1.5rem',
//               marginBottom: '1.5rem',
//               display: 'flex',
//               flexDirection: 'column',
//               gap: '1rem',
//             }}>
//               {/* Mode toggle */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                 <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                   Generation mode
//                 </span>
//                 <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                   border: '1px solid var(--border)' }}>
//                   {(['full', 'short_span'] as const).map(m => (
//                     <button key={m} onClick={() => setMode(m)} style={{
//                       padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                       background: mode === m ? 'var(--text)' : 'none',
//                       color: mode === m ? 'var(--bg)' : 'var(--text2)',
//                       border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                     }}>
//                       {m === 'full' ? 'Full Length Videos' : 'Short Span Clips'}
//                     </button>
//                   ))}
//                 </div>
//                 <Tooltip text={mode === 'full'
//                   ? 'Full pipeline: decomposition, multi-clip generation, img2vid chaining, stitching. Each Excel row = one full ad.'
//                   : 'Each Excel row = one discrete clip sent directly to Veo. No decomposition — you control each clip. Clips are chained and stitched into one video.'
//                 } />
//               </div>

//               {/* Short Span sub-toggle: Videos | Images */}
//               {mode === 'short_span' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip type
//                   </span>
//                   <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
//                     border: '1px solid var(--border)' }}>
//                     {(['video', 'image'] as const).map(t => (
//                       <button key={t} onClick={() => setShortSpanType(t)} style={{
//                         padding: '5px 14px', fontSize: 12, fontWeight: 500,
//                         background: shortSpanType === t ? 'var(--text)' : 'none',
//                         color: shortSpanType === t ? 'var(--bg)' : 'var(--text2)',
//                         border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {t === 'video' ? '▶  Short Videos' : '🖼  Static Images'}
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text={shortSpanType === 'video'
//                     ? 'Each row generates a short Veo video clip (2–8s). Clips are chained via img2vid and stitched.'
//                     : 'Each row generates a static image via Google Imagen. Images are animated with Ken Burns effect and crossfaded into one video. Silent output.'
//                   } />
//                 </div>
//               )}

//               {/* Clip duration — short_span video only */}
//               {mode === 'short_span' && shortSpanType === 'video' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Clip duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 3, 4, 5, 6, 8].map(d => (
//                       <button key={d} onClick={() => setClipDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: clipDuration === d ? 'var(--text)' : 'none',
//                         color: clipDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="Duration per clip sent to Veo (2–8 seconds). Total video = number of Excel rows × clip duration." />
//                 </div>
//               )}

//               {/* Hold duration — short_span image only */}
//               {mode === 'short_span' && shortSpanType === 'image' && (
//                 <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
//                   <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
//                     Hold duration
//                   </span>
//                   <div style={{ display: 'flex', gap: 6 }}>
//                     {[2, 5].map(d => (
//                       <button key={d} onClick={() => setHoldDuration(d)} style={{
//                         width: 36, height: 30, fontSize: 12, fontWeight: 500,
//                         borderRadius: 8,
//                         background: holdDuration === d ? 'var(--text)' : 'none',
//                         color: holdDuration === d ? 'var(--bg)' : 'var(--text2)',
//                         border: '1px solid var(--border)', cursor: 'pointer',
//                         fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {d}s
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="How long each image is held before crossfading to the next. Ken Burns animation plays during the hold. 2s for fast-paced, 5s for considered viewing." />
//                 </div>
//               )}

//               {/* No text / No speech */}
//               <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
//                 <CheckboxToggle
//                   label="No text overlay"
//                   checked={noText}
//                   onChange={setNoText}
//                   tooltip="Injects a guardrail instructing Veo to not render any text, captions, titles, subtitles, or watermarks in the video frame."
//                 />
//                 {/* No speech not applicable to static images */}
//                 {!(mode === 'short_span' && shortSpanType === 'image') && (
//                   <CheckboxToggle
//                     label="No speech / narration"
//                     checked={noSpeech}
//                     onChange={setNoSpeech}
//                     tooltip="Characters will not speak or lip-sync — narration plays as a voiceover in the background. Natural scene movement is preserved. Use when you want the narrator speaking over visuals without character dialogue."
//                   />
//                 )}

//                 <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
//                   <span style={{ fontSize: 12, color: 'var(--text2)', fontWeight: 500 }}>Refiner:</span>
//                   <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--pill)', overflow: 'hidden' }}>
//                     {([1, 2] as const).map(m => (
//                       <button key={m} onClick={() => setRefinerMode(m)} style={{
//                         padding: '4px 10px', fontSize: 11, fontWeight: 500, border: 'none',
//                         background: refinerMode === m ? 'var(--text)' : 'none',
//                         color: refinerMode === m ? 'var(--bg)' : 'var(--text2)',
//                         cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
//                       }}>
//                         {m === 1 ? 'Standard' : 'Lightweight'}
//                       </button>
//                     ))}
//                   </div>
//                   <Tooltip text="Standard: Nova 2 Lite → DeepSeek (higher quality). Lightweight: single fast call, also decomposes." />
//                 </div>              </div>
//             </div>

//             {/* Upload section */}
//             <div style={{ marginBottom: '1.75rem' }}>
//               <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
//                 <SectionLabel tooltip={mode === 'short_span'
//                   ? 'Short Span: each row = one clip. No decomposition. Clip duration is set from the toggle above.'
//                   : 'Full Length: each row = one full ad. The platform decomposes multi-clip ads automatically.'
//                 }>
//                   Upload prompts
//                 </SectionLabel>
//                 <button
//                   onClick={() => mode === 'short_span' ? downloadSampleShortSpan() : downloadSampleFull()}
//                   style={{
//                     fontSize: 12.5,
//                     fontWeight: 500,
//                     padding: '6px 14px',
//                     borderRadius: 'var(--pill)',
//                     border: '1px solid var(--border)',
//                     background: 'none',
//                     color: 'var(--text2)',
//                     cursor: 'pointer',
//                     fontFamily: 'inherit',
//                   }}
//                 >
//                   ↓ Sample Excel ({mode === 'short_span' ? 'Short Span' : 'Full Length'})
//                 </button>
//               </div>
//               <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
//                 {mode === 'short_span'
//                   ? 'One row per clip — prompt column only. Aspect ratio optional. Duration and task type are ignored.'
//                   : 'Columns: prompt, duration, aspect_ratio, task_type, priority.'}
//               </p>
//               <UploadZone onFile={handleFile} disabled={generating} />
//               {parseErr && (
//                 <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
//               )}
//             </div>

//             {/* Preview table */}
//             {preview.length > 0 && (
//               <>
//                 <PreviewTable rows={preview} mode={mode === 'short_span' && shortSpanType === 'image' ? 'short_span_image' : mode === 'short_span' ? 'short_span' : 'full'} clipDuration={clipDuration} />

//                 {/* Generate CTA */}
//                 <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
//                   {hasPermission(role, 'generate') ? (
//                     <button
//                       onClick={handleGenerate}
//                       disabled={generating || !file}
//                       style={{
//                         background: 'var(--text)',
//                         color: 'var(--bg)',
//                         border: 'none',
//                         borderRadius: 'var(--pill)',
//                         padding: '10px 28px',
//                         fontSize: 15,
//                         fontWeight: 600,
//                         cursor: generating ? 'not-allowed' : 'pointer',
//                         opacity: generating ? 0.45 : 1,
//                         fontFamily: 'inherit',
//                         transition: 'opacity .15s',
//                         display: 'flex',
//                         alignItems: 'center',
//                         gap: 8,
//                       }}
//                     >
//                       {generating
//                         ? 'Generating…'
//                         : mode === 'short_span' && shortSpanType === 'image'
//                         ? `🖼  Generate  ·  ${preview.length} image${preview.length !== 1 ? 's' : ''} · ${preview.length * holdDuration}s total`
//                         : mode === 'short_span'
//                         ? `▶  Generate  ·  ${preview.length} clip${preview.length !== 1 ? 's' : ''} · ${preview.length * clipDuration}s total`
//                         : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
//                     </button>
//                   ) : (
//                     <div className="alert alert-warn" style={{ margin: 0 }}>
//                       ⚠️  Your role cannot generate videos.
//                     </div>
//                   )}
//                   {!generating && preview.length > 0 && (
//                     <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
//                       {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
//                     </span>
//                   )}
//                   {refineErr && (
//                 <div style={{ fontSize: 13, color: 'var(--error)', padding: '8px 12px',
//                   background: '#ff3b3010', borderRadius: 8, marginBottom: 8 }}>
//                   Refinement failed: {refineErr}
//                 </div>
//               )}
//               {uploadErr && (
//                     <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
//                   )}
//                 </div>
//               </>
//             )}

//             {/* Video grid */}
//             <div ref={gridRef}>
//               {liveJob && (
//                 <VideoGrid
//                   job={liveJob}
//                   role={role}
//                   rejected={rejected}
//                   onReject={handleReject}
//                   onRerun={() => refetchJob()}
//                 />
//               )}
//             </div>
//           </>
//         )}

//         {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
//         {tab === 'youtube' && (
//           <>
//             <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
//               YouTube Queue
//             </SectionLabel>
//             <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
//               Approve a video card on the Generate tab to add it here.
//             </p>
//             <YouTubeQueue role={role} />
//           </>
//         )}

//         {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
//         {tab === 'users' && (
//           <UsersPanel />
//         )}

//         {tab === 'data' && (
//           <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
//             {hasPermission(role, 'view_jobs') && <JobsPanel />}
//             {hasPermission(role, 'view_metrics') && <MetricsPanel />}
//             {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
//               <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
//             )}
//           </div>
//         )}
//       </main>
//     </div>
//   )
// }




























// src/app/generate/page.tsx
'use client'
import { useState, useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { read, utils } from 'xlsx'

import { Navbar }       from '@/components/Navbar'
import { UploadZone, SectionLabel } from '@/components/UploadZone'
import { PreviewTable } from '@/components/PreviewTable'
import { VideoGrid }    from '@/components/VideoGrid'
import { JobsPanel }         from '@/components/JobsPanel'
import { RefinementOverlay } from '@/components/RefinementOverlay'
import { UsersPanel }   from '@/components/UsersPanel'
import { MetricsPanel } from '@/components/MetricsPanel'
import { YouTubeQueue } from '@/components/YouTubeQueue'
import { Tooltip }      from '@/components/Tooltip'

import { checkHealth, fetchJob, refinePrompts, approveJob, rejectJob } from '@/lib/api'
import { hasPermission } from '@/lib/permissions'
import type { Role, RefineResponse } from '@/types'
import type { Job, PreviewRow } from '@/types'

// ── Sample xlsx generation (client-side) ────────────────────────────────────
// Two separate sample files — one per mode — with appropriate columns and notes.

async function downloadSampleFull() {
  const { utils: x, writeFile } = await import('xlsx')
  const wb = x.book_new()
  const rows = [
    ['prompt', 'duration', 'aspect_ratio', 'task_type', 'priority'],
    [
      'NARRATOR: warm, Indian-accented female voice, calm and confident, mid-30s professional tone'
      + 'GROUP ANCHOR: Three Indian school students aged 14-16 in blue and white uniforms, silver laptops open.'
      + 'SCENE ANCHOR: Futuristic classroom, blue/purple AI holograms, neon-lit desks, large windows, daytime.'
      + 'CAMERA ANCHOR: Wide establishing shot from doorway, eye level, slow push-in.'
      + 'Curious students entering a futuristic classroom, glowing AI holograms floating around them.'
      + 'Indian Accent Narration: "The future belongs to creators, not just users."'
      + 'Students at glowing desks building chatbots and AI artwork, collaborative energy.'
      + 'Indian Accent Narration: "Learn Artificial Intelligence and build real projects."'
      + 'Fast montage: AI artwork on screen, chatbot on phone, student designing a website.'
      + 'Indian Accent Narration: "Create websites, games, avatars, and intelligent chatbots."'
      + 'Confident student presenting AI project, classmates applauding, scene holds still.'
      + 'Indian Accent Narration: "Start your AI journey today."',
      32, '9:16', 'AUTO', 1,
    ],
    [
      'NARRATOR: calm professional Indian male voice'
      + 'SCENE ANCHOR: Corporate boardroom, floor-to-ceiling glass, city skyline, evening light.'
      + 'CAMERA ANCHOR: Medium wide, eye level, slow push-in.'
      + 'Professionals reviewing AI dashboards on laptops, confident expressions.'
      + 'Narration: "What if your whole organisation could think smarter?"'
      + 'Team nodding, collaborative energy, AI analytics glowing on screens.'
      + 'Narration: "AI training for every leader, every team."'
      + 'Team smiling, city skyline behind them, scene holds still.'
      + 'Narration: "Build the future with your people."',
      24, '16:9', 'AUTO', 2,
    ],
  ]
  const ws = x.aoa_to_sheet(rows)
  ws['!cols'] = [{ wch: 80 }, { wch: 10 }, { wch: 14 }, { wch: 22 }, { wch: 10 }]
  x.book_append_sheet(wb, ws, 'prompts')
  writeFile(wb, 'veo_full_length_sample.xlsx')
}

async function downloadSampleShortSpan() {
  const { utils: x, writeFile } = await import('xlsx')
  const wb = x.book_new()
  // Each row = one clip. No duration column — set from UI slider.
  const rows = [
    ['prompt', 'aspect_ratio'],
    ['Wide shot of a school corridor, students walking purposefully, morning light, warm and vibrant atmosphere.', '9:16'],
    ['Close-up of student hands typing on a glowing laptop, colourful code on screen, focused expression, shallow depth of field.', '9:16'],
    ['Medium shot of a student looking at their screen with a delighted and surprised expression, soft smile, warm classroom light.', '9:16'],
    ['Close-up of a phone showing a chatbot conversation interface labelled "AI Assistant", finger scrolling, clean UI.', '9:16'],
    ['Three students gathered around a laptop pointing excitedly, laughing, creative energy, futuristic classroom background.', '9:16'],
    ['Wide shot of a student standing confidently in front of a large screen showing "AI Innovators Program", smiling at camera, scene holds still.', '9:16'],
  ]
  const ws = x.aoa_to_sheet(rows)
  ws['!cols'] = [{ wch: 90 }, { wch: 14 }]
  x.book_append_sheet(wb, ws, 'clips')
  // Reference sheet explaining the format
  const ref = x.aoa_to_sheet([
    ['SHORT SPAN CLIPS — Format Guide'],
    [''],
    ['Each row = one clip', 'No decomposition — you control every clip directly'],
    ['prompt', 'Scene description for this specific clip. Precise visuals. No narration lines.'],
    ['aspect_ratio', 'Reference only — 9:16, 16:9, 1:1. Set globally in veo.env.'],
    ['duration', 'NOT USED — clip duration set from the UI slider (2–8s per clip).'],
    ['task_type / priority', 'NOT USED — all rows are processed sequentially.'],
    [''],
    ['Clip chaining', 'Last frame of each clip anchors the next via img2vid.'],
    ['Total video', 'Rows × clip duration. E.g. 6 rows × 2s = 12s final video.'],
    ['No text / No speech', 'Set in UI — guardrail injected into all prompts automatically.'],
  ])
  ref['!cols'] = [{ wch: 28 }, { wch: 70 }]
  x.book_append_sheet(wb, ref, 'reference')
  writeFile(wb, 'veo_short_span_sample.xlsx')
}
// ── Parse Excel to preview rows ──────────────────────────────────────────────
function parseExcel(file: File): Promise<PreviewRow[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = e => {
      try {
        const data   = e.target?.result
        const wb     = read(data, { type: 'array' })
        const ws     = wb.Sheets[wb.SheetNames[0]]
        const raw    = utils.sheet_to_json(ws, { defval: '' }) as Record<string, unknown>[]
        // Normalise column names
        const rows: PreviewRow[] = raw
          .map(r => {
            const lower: Record<string, unknown> = {}
            for (const k of Object.keys(r)) lower[k.toLowerCase().trim()] = r[k]
            const dur = parseFloat(
              String(lower['duration'] ?? lower['duration_s'] ?? lower['duration_sec'] ?? '8')
            )
            return {
              prompt:       String(lower['prompt'] ?? '').trim(),
              duration:     isNaN(dur) ? 8 : Math.max(1, Math.min(120, Math.round(dur))),
              aspect_ratio: String(lower['aspect_ratio'] ?? '').trim() || undefined,
              task_type:    String(lower['task_type'] ?? lower['tasktype'] ?? 'AUTO').trim().toUpperCase() || 'AUTO',
              priority:     parseInt(String(lower['priority'] ?? lower['prio'] ?? '5')),
            }
          })
          .filter(r => r.prompt.length > 0 && !isNaN(r.duration))
        resolve(rows)
      } catch (err) {
        reject(err)
      }
    }
    reader.onerror = reject
    reader.readAsArrayBuffer(file)
  })
}

type Tab = 'generate' | 'youtube' | 'data' | 'users'

// ── Page ─────────────────────────────────────────────────────────────────────
// Local helper — avoids the `as const` readonly type conflict on setter functions
function CheckboxToggle({
  label, checked, onChange, tooltip,
}: {
  label:    string
  checked:  boolean
  onChange: (v: boolean) => void
  tooltip:  string
}) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8,
      cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={e => onChange(e.target.checked)}
        style={{ width: 15, height: 15, cursor: 'pointer', accentColor: 'var(--text)' }}
      />
      {label}
      <Tooltip text={tooltip} />
    </label>
  )
}

export default function GeneratePage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const role   = (session?.user?.role ?? 'viewer') as Role

  // Redirect unauthenticated
  useEffect(() => {
    if (status === 'unauthenticated') router.push('/login')
  }, [status, router])

  const [tab, setTab]             = useState<Tab>('generate')
  const [apiOk, setApiOk]         = useState<boolean | null>(null)
  const [file, setFile]           = useState<File | null>(null)
  const [preview, setPreview]     = useState<PreviewRow[]>([])
  const [parseErr, setParseErr]   = useState('')
  const [generating, setGenerating] = useState(false)
  const [uploadErr, setUploadErr]   = useState('')

  // Mode / feature toggles — placed before upload so user sets them first
  const [mode, setMode]               = useState<'full' | 'short_span' | 'short_span_image'>('full')

  // ── Refinement flow ─────────────────────────────────────────────────────────
  type FlowState = 'idle' | 'refining' | 'awaiting_approval' | 'generating'
  const [flowState, setFlowState]       = useState<FlowState>('idle')
  const [refineResult, setRefineResult] = useState<RefineResponse | null>(null)
  const [refinerMode, setRefinerMode]   = useState<1 | 2>(1)
  const [refineErr, setRefineErr]       = useState<string | null>(null)
  const [shortSpanType, setShortSpanType] = useState<'video' | 'image'>('video')
  const [clipDuration, setClipDuration]   = useState<number>(2)
  const [holdDuration, setHoldDuration]   = useState<number>(5)
  const [noText, setNoText]           = useState(false)
  const [noSpeech, setNoSpeech]       = useState(false)

  // Active job state
  const [activeJobId, setActiveJobId]     = useState<string | null>(null)
  const [lastJobId, setLastJobId]         = useState<string | null>(null)
  const [rejected, setRejected]           = useState<Set<string>>(new Set())

  // Polling
  const displayJobId = activeJobId ?? lastJobId
  const { data: liveJob, mutate: refetchJob } = useSWR<Job>(
    displayJobId ? `job-${displayJobId}` : null,
    () => fetchJob(displayJobId!),
    {
      refreshInterval: activeJobId ? 4000 : 0,
      onSuccess(job) {
        if (!['processing', 'pending'].includes(job.status)) {
          setLastJobId(job.job_id)
          setActiveJobId(null)
          setGenerating(false)
          // Final refetch after a short delay ensures all prompt results are
          // included — the job may flip to "completed" slightly before the
          // last result is written into the jobs dict.
          setTimeout(() => refetchJob(), 1500)
        }
      },
    },
  )

  // Video grid anchor ref for smooth scroll on generation start
  const gridRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (activeJobId) gridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [activeJobId])

  // API health check on mount
  useEffect(() => {
    checkHealth().then(ok => setApiOk(ok))
  }, [])

  async function handleFile(f: File) {
    setFile(f)
    setParseErr('')
    setPreview([])
    try {
      const rows = await parseExcel(f)
      setPreview(rows)
    } catch (err: unknown) {
      setParseErr(`Could not parse file: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function handleGenerate() {
    // Redirect to two-step refinement flow
    return handleRefineAndPreview()
  }

  async function handleRefineAndPreview() {
    if (!file) return
    setRefineErr(null)
    setFlowState('refining')
    setUploadErr('')
    setRejected(new Set())

    const apiMode = mode === 'short_span'
      ? (shortSpanType === 'image' ? 'short_span_image' : 'short_span')
      : 'full'

    try {
      const result = await refinePrompts(file, {
        mode:         apiMode,
        clipDuration,
        holdDuration,
        noText,
        noSpeech,
        refinerMode,
      })
      setRefineResult(result)
      setFlowState('awaiting_approval')
    } catch (err: unknown) {
      setRefineErr(err instanceof Error ? err.message : String(err))
      setFlowState('idle')
    }
  }

  async function handleApprove(approvedRows: { rowIndex: number; finalPrompt: string }[]) {
    if (!refineResult) return
    setFlowState('generating')
    setGenerating(true)
    try {
      const { jobId } = await approveJob(refineResult.jobId, approvedRows)
      setActiveJobId(jobId)
      setTab('generate')
    } catch (err: unknown) {
      setRefineErr(err instanceof Error ? err.message : String(err))
      setFlowState('idle')
      setGenerating(false)
    }
  }

  async function handleRejectRefinement() {
    if (refineResult) {
      await rejectJob(refineResult.jobId).catch(() => {})
    }
    setRefineResult(null)
    setFlowState('idle')
  }

  function handleReject(jobId: string, index: number) {
    setRejected(prev => new Set([...prev, `${jobId}-${index}`]))
  }

  // In short span mode, duration and clip count come from UI settings, not Excel
  const isShortSpanMode = mode === 'short_span' || mode === 'short_span_image'
  const totalClips = isShortSpanMode
    ? preview.length
    : preview.reduce((a, r) => a + Math.ceil((r.duration || 8) / 8), 0)
  const totalDur = isShortSpanMode
    ? preview.length * (mode === 'short_span_image' ? holdDuration : clipDuration)
    : preview.reduce((a, r) => a + (r.duration || 8), 0)

  if (status === 'loading') return null

  return (
    <div style={{ minHeight: '100dvh', background: 'var(--bg)' }}>
      {flowState === 'awaiting_approval' && refineResult && (
        <RefinementOverlay
          jobId={refineResult.jobId}
          rows={refineResult.rows}
          refinerMode={refinerMode}
          onApprove={handleApprove}
          onReject={handleRejectRefinement}
        />
      )}
      <Navbar />

      {/* Tab bar */}
      <div
        style={{
          borderBottom: '1px solid var(--border)',
          padding: '0 2rem',
          display: 'flex',
          gap: 0,
        }}
      >
        {([
          ['generate', 'Generate'],
          ['youtube',  'YouTube Queue'],
          ['data',     'Jobs & Metrics'],
          ...(hasPermission(role, 'view_jobs') ? [['users', 'Users']] as [Tab, string][] : []),
        ] as [Tab, string][]).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              fontSize: 13.5,
              fontWeight: 500,
              padding: '10px 16px',
              background: 'none',
              border: 'none',
              borderBottom: `2px solid ${tab === id ? 'var(--text)' : 'transparent'}`,
              color: tab === id ? 'var(--text)' : 'var(--text2)',
              cursor: 'pointer',
              fontFamily: 'inherit',
              transition: 'color .15s',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <main style={{ maxWidth: 1160, margin: '0 auto', padding: '2.5rem 2rem 4rem' }}>

        {/* ── Tab: Generate ─────────────────────────────────────────────────── */}
        {tab === 'generate' && (
          <>
            {/* API status */}
            {apiOk === false && (
              <div className="alert alert-error" style={{ marginBottom: '1.5rem' }}>
                ✕  Cannot reach API on port 8100 — start <code>python veo_main.py</code> first.
              </div>
            )}

            {/* ── Mode & options — set BEFORE uploading ── */}
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border2)',
              borderRadius: 'var(--radius-lg)',
              padding: '1.25rem 1.5rem',
              marginBottom: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}>
              {/* Mode toggle */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
                  Generation mode
                </span>
                <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
                  border: '1px solid var(--border)' }}>
                  {(['full', 'short_span'] as const).map(m => (
                    <button key={m} onClick={() => setMode(m)} style={{
                      padding: '5px 14px', fontSize: 12, fontWeight: 500,
                      background: mode === m ? 'var(--text)' : 'none',
                      color: mode === m ? 'var(--bg)' : 'var(--text2)',
                      border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
                    }}>
                      {m === 'full' ? 'Full Length Videos' : 'Short Span Clips'}
                    </button>
                  ))}
                </div>
                <Tooltip text={mode === 'full'
                  ? 'Full pipeline: decomposition, multi-clip generation, img2vid chaining, stitching. Each Excel row = one full ad.'
                  : 'Each Excel row = one discrete clip sent directly to Veo. No decomposition — you control each clip. Clips are chained and stitched into one video.'
                } />
              </div>

              {/* Short Span sub-toggle: Videos | Images */}
              {mode === 'short_span' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
                    Clip type
                  </span>
                  <div style={{ display: 'flex', borderRadius: 'var(--pill)', overflow: 'hidden',
                    border: '1px solid var(--border)' }}>
                    {(['video', 'image'] as const).map(t => (
                      <button key={t} onClick={() => setShortSpanType(t)} style={{
                        padding: '5px 14px', fontSize: 12, fontWeight: 500,
                        background: shortSpanType === t ? 'var(--text)' : 'none',
                        color: shortSpanType === t ? 'var(--bg)' : 'var(--text2)',
                        border: 'none', cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
                      }}>
                        {t === 'video' ? '▶  Short Videos' : '🖼  Static Images'}
                      </button>
                    ))}
                  </div>
                  <Tooltip text={shortSpanType === 'video'
                    ? 'Each row generates a short Veo video clip (2–8s). Clips are chained via img2vid and stitched.'
                    : 'Each row generates a static image via Google Imagen. Images are animated with Ken Burns effect and crossfaded into one video. Silent output.'
                  } />
                </div>
              )}

              {/* Clip duration — short_span video only */}
              {mode === 'short_span' && shortSpanType === 'video' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
                    Clip duration
                  </span>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[2, 3, 4, 5, 6, 8].map(d => (
                      <button key={d} onClick={() => setClipDuration(d)} style={{
                        width: 36, height: 30, fontSize: 12, fontWeight: 500,
                        borderRadius: 8,
                        background: clipDuration === d ? 'var(--text)' : 'none',
                        color: clipDuration === d ? 'var(--bg)' : 'var(--text2)',
                        border: '1px solid var(--border)', cursor: 'pointer',
                        fontFamily: 'inherit', transition: 'all .15s',
                      }}>
                        {d}s
                      </button>
                    ))}
                  </div>
                  <Tooltip text="Duration per clip sent to Veo (2–8 seconds). Total video = number of Excel rows × clip duration." />
                </div>
              )}

              {/* Hold duration — short_span image only */}
              {mode === 'short_span' && shortSpanType === 'image' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', minWidth: 130 }}>
                    Hold duration
                  </span>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[2, 5].map(d => (
                      <button key={d} onClick={() => setHoldDuration(d)} style={{
                        width: 36, height: 30, fontSize: 12, fontWeight: 500,
                        borderRadius: 8,
                        background: holdDuration === d ? 'var(--text)' : 'none',
                        color: holdDuration === d ? 'var(--bg)' : 'var(--text2)',
                        border: '1px solid var(--border)', cursor: 'pointer',
                        fontFamily: 'inherit', transition: 'all .15s',
                      }}>
                        {d}s
                      </button>
                    ))}
                  </div>
                  <Tooltip text="How long each image is held before crossfading to the next. Ken Burns animation plays during the hold. 2s for fast-paced, 5s for considered viewing." />
                </div>
              )}

              {/* No text / No speech */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                <CheckboxToggle
                  label="No text overlay"
                  checked={noText}
                  onChange={setNoText}
                  tooltip="Injects a guardrail instructing Veo to not render any text, captions, titles, subtitles, or watermarks in the video frame."
                />
                {/* No speech not applicable to static images */}
                {!(mode === 'short_span' && shortSpanType === 'image') && (
                  <CheckboxToggle
                    label="No speech / narration"
                    checked={noSpeech}
                    onChange={setNoSpeech}
                    tooltip="Characters will not speak or lip-sync — narration plays as a voiceover in the background. Natural scene movement is preserved. Use when you want the narrator speaking over visuals without character dialogue."
                  />
                )}

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 12, color: 'var(--text2)', fontWeight: 500 }}>Refiner:</span>
                  <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--pill)', overflow: 'hidden' }}>
                    {([1, 2] as const).map(m => (
                      <button key={m} onClick={() => setRefinerMode(m)} style={{
                        padding: '4px 10px', fontSize: 11, fontWeight: 500, border: 'none',
                        background: refinerMode === m ? 'var(--text)' : 'none',
                        color: refinerMode === m ? 'var(--bg)' : 'var(--text2)',
                        cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
                      }}>
                        {m === 1 ? 'Standard' : 'Lightweight'}
                      </button>
                    ))}
                  </div>
                  <Tooltip text="Standard: Nova 2 Lite → DeepSeek (higher quality). Lightweight: single fast call, also decomposes." />
                </div>              </div>
            </div>

            {/* Upload section */}
            <div style={{ marginBottom: '1.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
                <SectionLabel tooltip={mode === 'short_span'
                  ? 'Short Span: each row = one clip. No decomposition. Clip duration is set from the toggle above.'
                  : 'Full Length: each row = one full ad. The platform decomposes multi-clip ads automatically.'
                }>
                  Upload prompts
                </SectionLabel>
                <button
                  onClick={() => mode === 'short_span' ? downloadSampleShortSpan() : downloadSampleFull()}
                  style={{
                    fontSize: 12.5,
                    fontWeight: 500,
                    padding: '6px 14px',
                    borderRadius: 'var(--pill)',
                    border: '1px solid var(--border)',
                    background: 'none',
                    color: 'var(--text2)',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  ↓ Sample Excel ({mode === 'short_span' ? 'Short Span' : 'Full Length'})
                </button>
              </div>
              <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1rem', marginTop: 0 }}>
                {mode === 'short_span'
                  ? 'One row per clip — prompt column only. Aspect ratio optional. Duration and task type are ignored.'
                  : 'Columns: prompt, duration, aspect_ratio, task_type, priority.'}
              </p>
              <UploadZone onFile={handleFile} disabled={generating} />
              {parseErr && (
                <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{parseErr}</div>
              )}
            </div>

            {/* Preview table */}
            {preview.length > 0 && (
              <>
                <PreviewTable rows={preview} mode={mode === 'short_span' && shortSpanType === 'image' ? 'short_span_image' : mode === 'short_span' ? 'short_span' : 'full'} clipDuration={clipDuration} />

                {/* Generate CTA */}
                <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                  {hasPermission(role, 'generate') ? (
                    <button
                      onClick={handleGenerate}
                      disabled={generating || !file}
                      style={{
                        background: 'var(--text)',
                        color: 'var(--bg)',
                        border: 'none',
                        borderRadius: 'var(--pill)',
                        padding: '10px 28px',
                        fontSize: 15,
                        fontWeight: 600,
                        cursor: generating ? 'not-allowed' : 'pointer',
                        opacity: generating ? 0.45 : 1,
                        fontFamily: 'inherit',
                        transition: 'opacity .15s',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}
                    >
                      {generating
                        ? 'Generating…'
                        : mode === 'short_span' && shortSpanType === 'image'
                        ? `🖼  Generate  ·  ${preview.length} image${preview.length !== 1 ? 's' : ''} · ${preview.length * holdDuration}s total`
                        : mode === 'short_span'
                        ? `▶  Generate  ·  ${preview.length} clip${preview.length !== 1 ? 's' : ''} · ${preview.length * clipDuration}s total`
                        : `▶  Generate  ·  ${preview.length} prompt${preview.length !== 1 ? 's' : ''}`}
                    </button>
                  ) : (
                    <div className="alert alert-warn" style={{ margin: 0 }}>
                      ⚠️  Your role cannot generate videos.
                    </div>
                  )}
                  {!generating && preview.length > 0 && (
                    <span style={{ fontSize: 12.5, color: 'var(--text2)' }}>
                      {totalDur}s total · {totalClips} clip{totalClips !== 1 ? 's' : ''}
                    </span>
                  )}
                  {refineErr && (
                <div style={{ fontSize: 13, color: 'var(--error)', padding: '8px 12px',
                  background: '#ff3b3010', borderRadius: 8, marginBottom: 8 }}>
                  Refinement failed: {refineErr}
                </div>
              )}
              {uploadErr && (
                    <span style={{ fontSize: 12.5, color: 'var(--error)' }}>{uploadErr}</span>
                  )}
                </div>
              </>
            )}

            {/* Video grid */}
            <div ref={gridRef}>
              {liveJob && (
                <VideoGrid
                  job={liveJob}
                  role={role}
                  rejected={rejected}
                  onReject={handleReject}
                  onRerun={() => refetchJob()}
                />
              )}
            </div>
          </>
        )}

        {/* ── Tab: YouTube Queue ────────────────────────────────────────────── */}
        {tab === 'youtube' && (
          <>
            <SectionLabel tooltip="Videos you've approved appear here for editing metadata before uploading to YouTube.">
              YouTube Queue
            </SectionLabel>
            <p style={{ fontSize: 13.5, color: 'var(--text2)', marginBottom: '1.5rem', marginTop: '0.3rem' }}>
              Approve a video card on the Generate tab to add it here.
            </p>
            <YouTubeQueue role={role} />
          </>
        )}

        {/* ── Tab: Jobs & Metrics ───────────────────────────────────────────── */}
        {tab === 'users' && (
          <UsersPanel />
        )}

        {tab === 'data' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {hasPermission(role, 'view_jobs') && <JobsPanel />}
            {hasPermission(role, 'view_metrics') && <MetricsPanel />}
            {!hasPermission(role, 'view_jobs') && !hasPermission(role, 'view_metrics') && (
              <div className="alert alert-warn">⚠️  Your role cannot view jobs or metrics.</div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}