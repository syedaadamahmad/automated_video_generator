// // src/components/RefinementOverlay.tsx
// // Full-screen refinement overlay shown after LLM refines prompts.
// // State contract:
// //   - freeText and structured states are COMPLETELY independent — never sync
// //   - activeVersion tracks the last-edited mode → determines what gets approved
// //   - switching edit modes preserves all edits made in either mode
// 'use client'
// import { useCallback, useState } from 'react'
// import type { RefinedRow, RowEditState, StructuredFields } from '@/types'
// import { refineRowAgain } from '@/lib/api'

// interface Props {
//   jobId:       string
//   rows:        RefinedRow[]
//   refinerMode: 1 | 2
//   onApprove:   (approvedRows: { rowIndex: number; finalPrompt: string }[]) => void
//   onReject:    () => void
// }

// // ── Helpers ────────────────────────────────────────────────────────────────────
// function structuredToPrompt(s: StructuredFields): string {
//   const parts = [
//     s.scene        && `SCENE: ${s.scene}`,
//     s.characters   && `CHARACTERS: ${s.characters}`,
//     s.camera       && `CAMERA: ${s.camera}`,
//     s.lighting     && `LIGHTING: ${s.lighting}`,
//     s.mythologyNotes && s.mythologyNotes,
//     s.narrationLines.length > 0 &&
//       s.narrationLines.map(l => `Narration "${l}"`).join(' '),
//   ].filter(Boolean)
//   return parts.join('. ')
// }

// function initRowState(row: RefinedRow): RowEditState {
//   return {
//     rowIndex:        row.rowIndex,
//     freeText:        row.refinedPrompt,
//     freeTextDirty:   false,
//     structured:      { ...row.structured, narrationLines: [...row.structured.narrationLines] },
//     structuredDirty: false,
//     activeVersion:   'refined',
//     editMode:        'freetext',
//     isExpanded:      row.rowIndex === 0,   // first card open by default
//     isRefining:      false,
//   }
// }

// function getFinalPrompt(row: RefinedRow, state: RowEditState): string {
//   if (state.activeVersion === 'freetext')   return state.freeText
//   if (state.activeVersion === 'structured') return structuredToPrompt(state.structured)
//   return row.refinedPrompt
// }

// // ── Colours ────────────────────────────────────────────────────────────────────
// const C = {
//   warning:   '#FF9F0A',
//   mythology: '#BF5AF2',
//   accent:    'var(--accent)',
//   error:     'var(--error)',
//   text:      'var(--text)',
//   text2:     'var(--text2)',
//   text3:     'var(--text3)',
//   border:    'var(--border)',
//   border2:   'var(--border2)',
//   surface:   'var(--surface)',
//   surface2:  'var(--surface2)',
// }

// // ── Main component ─────────────────────────────────────────────────────────────
// export function RefinementOverlay({ jobId, rows, refinerMode, onApprove, onReject }: Props) {
//   const [states, setStates] = useState<RowEditState[]>(() => rows.map(initRowState))
//   const [approving, setApproving] = useState(false)

//   function updateState(idx: number, patch: Partial<RowEditState>) {
//     setStates(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s))
//   }

//   // ── Free text edit ─────────────────────────────────────────────────────────
//   function onFreeTextChange(idx: number, value: string) {
//     updateState(idx, {
//       freeText:      value,
//       freeTextDirty: true,
//       activeVersion: 'freetext',
//     })
//   }

//   // ── Structured edit ────────────────────────────────────────────────────────
//   function onStructuredChange(idx: number, field: keyof StructuredFields, value: string | string[]) {
//     setStates(prev => prev.map((s, i) => {
//       if (i !== idx) return s
//       return {
//         ...s,
//         structured:      { ...s.structured, [field]: value },
//         structuredDirty: true,
//         activeVersion:   'structured',
//       }
//     }))
//   }

//   function onNarrationLineChange(idx: number, lineIdx: number, value: string) {
//     setStates(prev => prev.map((s, i) => {
//       if (i !== idx) return s
//       const lines = [...s.structured.narrationLines]
//       lines[lineIdx] = value
//       return {
//         ...s,
//         structured:      { ...s.structured, narrationLines: lines },
//         structuredDirty: true,
//         activeVersion:   'structured',
//       }
//     }))
//   }

//   function addNarrationLine(idx: number) {
//     setStates(prev => prev.map((s, i) => {
//       if (i !== idx) return s
//       const lines = [...s.structured.narrationLines, '']
//       return { ...s, structured: { ...s.structured, narrationLines: lines }, structuredDirty: true, activeVersion: 'structured' }
//     }))
//   }

//   function removeNarrationLine(idx: number, lineIdx: number) {
//     setStates(prev => prev.map((s, i) => {
//       if (i !== idx) return s
//       const lines = s.structured.narrationLines.filter((_, li) => li !== lineIdx)
//       return { ...s, structured: { ...s.structured, narrationLines: lines }, structuredDirty: true, activeVersion: 'structured' }
//     }))
//   }

//   // ── Refine Again ───────────────────────────────────────────────────────────
//   const handleRefineAgain = useCallback(async (idx: number) => {
//     updateState(idx, { isRefining: true })
//     try {
//       const refreshed = await refineRowAgain(jobId, idx)
//       setStates(prev => prev.map((s, i) => {
//         if (i !== idx) return s
//         // Reset BOTH edit states to new LLM output
//         return {
//           ...s,
//           freeText:        refreshed.refinedPrompt,
//           freeTextDirty:   false,
//           structured:      { ...refreshed.structured, narrationLines: [...refreshed.structured.narrationLines] },
//           structuredDirty: false,
//           activeVersion:   'refined',
//           isRefining:      false,
//         }
//       }))
//     } catch {
//       updateState(idx, { isRefining: false })
//     }
//   }, [jobId])

//   // ── Approve ────────────────────────────────────────────────────────────────
//   async function handleApprove() {
//     setApproving(true)
//     const approvedRows = rows.map((row, idx) => ({
//       rowIndex:    row.rowIndex,
//       finalPrompt: getFinalPrompt(row, states[idx]),
//     }))
//     onApprove(approvedRows)
//   }

//   return (
//     <div style={{
//       position: 'fixed', inset: 0, zIndex: 1000,
//       background: 'var(--bg)', display: 'flex', flexDirection: 'column',
//     }}>
//       {/* ── Header ── */}
//       <div style={{
//         padding: '16px 24px', borderBottom: `1px solid ${C.border}`,
//         display: 'flex', alignItems: 'center', justifyContent: 'space-between',
//         background: 'var(--bg)', flexShrink: 0,
//       }}>
//         <div>
//           <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: C.text }}>
//             Review Refined Prompts
//           </h2>
//           <p style={{ fontSize: 12, color: C.text2, margin: '2px 0 0' }}>
//             {rows.length} row{rows.length !== 1 ? 's' : ''} refined
//             {refinerMode === 2 ? ' · Mode 2 (lightweight)' : ' · Mode 1 (standard)'}
//             · Approve to begin generation
//           </p>
//         </div>
//         <div style={{ display: 'flex', gap: 10 }}>
//           <button onClick={onReject} style={btnStyle('ghost')}>
//             ✕ Reject — back to upload
//           </button>
//           <button
//             onClick={handleApprove}
//             disabled={approving}
//             style={btnStyle('primary', approving)}
//           >
//             {approving ? 'Starting…' : '✓ Approve & Generate'}
//           </button>
//         </div>
//       </div>

//       {/* ── Scrollable cards ── */}
//       <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
//         <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
//           {rows.map((row, idx) => (
//             <RowCard
//               key={row.rowIndex}
//               row={row}
//               state={states[idx]}
//               onToggleExpand={() => updateState(idx, { isExpanded: !states[idx].isExpanded })}
//               onEditModeToggle={(m) => updateState(idx, { editMode: m })}
//               onFreeTextChange={(v) => onFreeTextChange(idx, v)}
//               onStructuredChange={(f, v) => onStructuredChange(idx, f, v)}
//               onNarrationLineChange={(li, v) => onNarrationLineChange(idx, li, v)}
//               onAddNarrationLine={() => addNarrationLine(idx)}
//               onRemoveNarrationLine={(li) => removeNarrationLine(idx, li)}
//               onRefineAgain={() => handleRefineAgain(idx)}
//             />
//           ))}
//         </div>
//       </div>

//       {/* ── Footer summary ── */}
//       <div style={{
//         padding: '12px 24px', borderTop: `1px solid ${C.border}`,
//         display: 'flex', alignItems: 'center', gap: 20, flexShrink: 0,
//         fontSize: 12, color: C.text2,
//       }}>
//         <span>
//           {states.filter(s => s.freeTextDirty || s.structuredDirty).length} row(s) edited
//         </span>
//         <span>
//           {rows.filter(r => r.mythologyDetected).length > 0 &&
//             `🔮 ${rows.filter(r => r.mythologyDetected).length} mythology style lock(s) applied`}
//         </span>
//         <span style={{ marginLeft: 'auto' }}>
//           Total duration: {rows.reduce((sum, r) => sum + r.duration, 0)}s
//         </span>
//       </div>
//     </div>
//   )
// }

// // ── Row Card ───────────────────────────────────────────────────────────────────
// interface CardProps {
//   row:                   RefinedRow
//   state:                 RowEditState
//   onToggleExpand:        () => void
//   onEditModeToggle:      (m: 'freetext' | 'structured') => void
//   onFreeTextChange:      (v: string) => void
//   onStructuredChange:    (f: keyof StructuredFields, v: string | string[]) => void
//   onNarrationLineChange: (li: number, v: string) => void
//   onAddNarrationLine:    () => void
//   onRemoveNarrationLine: (li: number) => void
//   onRefineAgain:         () => void
// }

// function RowCard({
//   row, state,
//   onToggleExpand, onEditModeToggle, onFreeTextChange,
//   onStructuredChange, onNarrationLineChange, onAddNarrationLine,
//   onRemoveNarrationLine, onRefineAgain,
// }: CardProps) {
//   const hasEdits    = state.freeTextDirty || state.structuredDirty
//   const totalDurS   = row.clips.length > 0 ? row.clips[row.clips.length - 1].endS : row.duration
//   const durationStr = row.clips.length > 0
//     ? `${row.clips.length} clip${row.clips.length !== 1 ? 's' : ''} · ${totalDurS}s total`
//     : `${row.duration}s`

//   return (
//     <div style={{
//       border: `1px solid ${hasEdits ? C.accent : C.border2}`,
//       borderRadius: 12,
//       background: C.surface,
//       overflow: 'hidden',
//       transition: 'border-color .15s',
//     }}>
//       {/* Card header */}
//       <button
//         onClick={onToggleExpand}
//         style={{
//           width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
//           padding: '14px 16px', background: 'none', border: 'none',
//           cursor: 'pointer', textAlign: 'left',
//         }}
//       >
//         <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
//           <span style={{
//             fontSize: 11, fontWeight: 600, padding: '2px 8px',
//             borderRadius: 20, background: C.surface2, color: C.text2,
//           }}>
//             Row {row.rowNumber}
//           </span>
//           {row.mythologyDetected && (
//             <span style={{ fontSize: 11, color: C.mythology }}>🔮 mythology</span>
//           )}
//           {hasEdits && (
//             <span style={{ fontSize: 11, color: C.accent }}>✎ edited</span>
//           )}
//           {row.warnings.length > 0 && (
//             <span style={{ fontSize: 11, color: C.warning }}>
//               ⚠ {row.warnings.length} warning{row.warnings.length > 1 ? 's' : ''}
//             </span>
//           )}
//           <span style={{ fontSize: 12, color: C.text2, maxWidth: 360,
//             overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
//             {row.originalPrompt.slice(0, 80)}{row.originalPrompt.length > 80 ? '…' : ''}
//           </span>
//         </div>
//         <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
//           <span style={{ fontSize: 11, color: C.text3 }}>{durationStr}</span>
//           <span style={{ fontSize: 14, color: C.text3 }}>{state.isExpanded ? '▲' : '▼'}</span>
//         </div>
//       </button>

//       {state.isExpanded && (
//         <div style={{ padding: '0 16px 16px', borderTop: `1px solid ${C.border}` }}>
//           {/* Clip timestamps */}
//           {row.clips.length > 0 && (
//             <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12, marginBottom: 14 }}>
//               {row.clips.map(clip => (
//                 <span key={clip.clip} style={{
//                   fontSize: 10, fontWeight: 500, padding: '3px 8px',
//                   borderRadius: 6, background: C.surface2,
//                   border: `1px solid ${C.border}`, color: C.text3,
//                 }}>
//                   {clip.label}
//                 </span>
//               ))}
//             </div>
//           )}

//           {/* Warnings */}
//           {row.warnings.length > 0 && (
//             <div style={{ marginBottom: 12 }}>
//               {row.warnings.map((w, i) => (
//                 <div key={i} style={{
//                   fontSize: 11, color: C.warning, padding: '5px 10px',
//                   background: `${C.warning}15`, borderRadius: 6,
//                   marginBottom: 4,
//                 }}>
//                   ⚠ {w}
//                 </div>
//               ))}
//             </div>
//           )}

//           {/* Edit mode toggle + Refine Again */}
//           <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
//             <div style={{
//               display: 'flex', borderRadius: 20, overflow: 'hidden',
//               border: `1px solid ${C.border}`,
//             }}>
//               {(['freetext', 'structured'] as const).map(m => (
//                 <button
//                   key={m}
//                   onClick={() => onEditModeToggle(m)}
//                   style={{
//                     padding: '4px 14px', fontSize: 12, fontWeight: 500,
//                     background: state.editMode === m ? C.text : 'none',
//                     color: state.editMode === m ? 'var(--bg)' : C.text2,
//                     border: 'none', cursor: 'pointer', fontFamily: 'inherit',
//                     transition: 'all .15s',
//                   }}
//                 >
//                   {m === 'freetext' ? 'Free Text' : 'Structured'}
//                   {m === 'freetext' && state.freeTextDirty && ' ✎'}
//                   {m === 'structured' && state.structuredDirty && ' ✎'}
//                 </button>
//               ))}
//             </div>
//             <button
//               onClick={onRefineAgain}
//               disabled={state.isRefining}
//               style={{
//                 fontSize: 11, padding: '4px 12px',
//                 borderRadius: 20, border: `1px solid ${C.border}`,
//                 background: 'none', color: C.text2,
//                 cursor: state.isRefining ? 'not-allowed' : 'pointer',
//                 opacity: state.isRefining ? 0.5 : 1, fontFamily: 'inherit',
//               }}
//             >
//               {state.isRefining ? 'Refining…' : '↻ Refine Again'}
//             </button>
//           </div>

//           {/* Active version indicator */}
//           <div style={{ fontSize: 10, color: C.text3, marginBottom: 8 }}>
//             Will send:{' '}
//             <span style={{ color: state.activeVersion === 'refined' ? C.text2 : C.accent, fontWeight: 500 }}>
//               {state.activeVersion === 'refined'
//                 ? 'LLM-refined version (no edits)'
//                 : state.activeVersion === 'freetext'
//                 ? 'Your free text edits'
//                 : 'Your structured edits'}
//             </span>
//           </div>

//           {/* ── Free text editor ── */}
//           {state.editMode === 'freetext' && (
//             <textarea
//               value={state.freeText}
//               onChange={e => onFreeTextChange(e.target.value)}
//               rows={8}
//               style={{
//                 width: '100%', background: C.surface2,
//                 border: `1px solid ${state.freeTextDirty ? C.accent : C.border}`,
//                 borderRadius: 8, padding: '10px 12px',
//                 fontSize: 13, color: C.text, fontFamily: 'inherit',
//                 resize: 'vertical', outline: 'none', boxSizing: 'border-box',
//                 lineHeight: 1.6,
//               }}
//             />
//           )}

//           {/* ── Structured editor ── */}
//           {state.editMode === 'structured' && (
//             <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
//               {(
//                 [
//                   ['scene',      'Scene'],
//                   ['characters', 'Characters'],
//                   ['camera',     'Camera'],
//                   ['lighting',   'Lighting'],
//                   ['mythologyNotes', 'Mythology Style Notes'],
//                 ] as [keyof StructuredFields, string][]
//               ).map(([field, label]) => (
//                 <div key={field}>
//                   <label style={labelStyle}>{label}</label>
//                   <textarea
//                     value={state.structured[field] as string}
//                     onChange={e => onStructuredChange(field, e.target.value)}
//                     rows={field === 'mythologyNotes' ? 4 : 2}
//                     style={{
//                       width: '100%', background: C.surface2,
//                       border: `1px solid ${state.structuredDirty ? C.accent : C.border}`,
//                       borderRadius: 6, padding: '7px 10px',
//                       fontSize: 12, color: C.text, fontFamily: 'inherit',
//                       resize: 'vertical', outline: 'none', boxSizing: 'border-box',
//                     }}
//                   />
//                 </div>
//               ))}

//               {/* Narration lines */}
//               <div>
//                 <label style={labelStyle}>Narration Lines</label>
//                 <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
//                   {state.structured.narrationLines.map((line, li) => (
//                     <div key={li} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
//                       <span style={{ fontSize: 10, color: C.text3, paddingTop: 8, minWidth: 20 }}>
//                         {li + 1}.
//                       </span>
//                       <textarea
//                         value={line}
//                         onChange={e => onNarrationLineChange(li, e.target.value)}
//                         rows={2}
//                         style={{
//                           flex: 1, background: C.surface2,
//                           border: `1px solid ${state.structuredDirty ? C.accent : C.border}`,
//                           borderRadius: 6, padding: '7px 10px',
//                           fontSize: 12, color: C.text, fontFamily: 'inherit',
//                           resize: 'vertical', outline: 'none', boxSizing: 'border-box',
//                         }}
//                       />
//                       <button
//                         onClick={() => onRemoveNarrationLine(li)}
//                         style={{
//                           padding: '4px 8px', fontSize: 11, borderRadius: 6,
//                           border: `1px solid ${C.border}`, background: 'none',
//                           color: C.error, cursor: 'pointer', fontFamily: 'inherit',
//                           marginTop: 4,
//                         }}
//                       >
//                         ✕
//                       </button>
//                     </div>
//                   ))}
//                   <button
//                     onClick={onAddNarrationLine}
//                     style={{
//                       fontSize: 11, padding: '5px 12px', borderRadius: 6,
//                       border: `1px solid ${C.border}`, background: 'none',
//                       color: C.text2, cursor: 'pointer', fontFamily: 'inherit',
//                       alignSelf: 'flex-start',
//                     }}
//                   >
//                     + Add line
//                   </button>
//                 </div>
//               </div>
//             </div>
//           )}

//           {/* Mythology lock info */}
//           {row.mythologyDetected && (
//             <div style={{
//               marginTop: 12, fontSize: 11, color: C.mythology,
//               padding: '6px 10px', background: `${C.mythology}10`,
//               borderRadius: 6, borderLeft: `3px solid ${C.mythology}`,
//             }}>
//               🔮 Indian mythology visual style lock automatically applied.
//               Edit in Mythology Style Notes (structured mode) if needed.
//             </div>
//           )}
//         </div>
//       )}
//     </div>
//   )
// }

// // ── Style helpers ──────────────────────────────────────────────────────────────
// const labelStyle: React.CSSProperties = {
//   display: 'block', fontSize: 11, fontWeight: 500,
//   color: 'var(--text2)', marginBottom: 4,
// }

// function btnStyle(variant: 'primary' | 'ghost', disabled = false): React.CSSProperties {
//   const base: React.CSSProperties = {
//     fontSize: 13, fontWeight: 500, padding: '8px 18px',
//     borderRadius: 'var(--pill)', cursor: disabled ? 'not-allowed' : 'pointer',
//     fontFamily: 'inherit', opacity: disabled ? 0.5 : 1,
//     transition: 'all .15s', border: '1px solid var(--border)',
//   }
//   if (variant === 'primary') return { ...base, background: 'var(--text)', color: 'var(--bg)', border: 'none' }
//   return { ...base, background: 'none', color: 'var(--text2)' }
// }


























// src/components/RefinementOverlay.tsx
// Full-screen refinement overlay shown after LLM refines prompts.
// State contract:
//   - freeText and structured states are COMPLETELY independent — never sync
//   - activeVersion tracks the last-edited mode → determines what gets approved
//   - switching edit modes preserves all edits made in either mode
'use client'
import { useCallback, useState } from 'react'
import type { RefinedRow, RowEditState, StructuredFields } from '@/types'
import { refineRowAgain } from '@/lib/api'

interface Props {
  jobId:       string
  rows:        RefinedRow[]
  refinerMode: 1 | 2
  onApprove:   (approvedRows: { rowIndex: number; finalPrompt: string }[]) => void
  onReject:    () => void
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function structuredToPrompt(s: StructuredFields): string {
  const parts = [
    s.scene        && `SCENE: ${s.scene}`,
    s.characters   && `CHARACTERS: ${s.characters}`,
    s.camera       && `CAMERA: ${s.camera}`,
    s.lighting     && `LIGHTING: ${s.lighting}`,
    s.mythologyNotes && s.mythologyNotes,
    s.narrationLines.length > 0 &&
      s.narrationLines.map(l => `Narration "${l}"`).join(' '),
  ].filter(Boolean)
  return parts.join('. ')
}

function initRowState(row: RefinedRow): RowEditState {
  return {
    rowIndex:        row.rowIndex,
    freeText:        row.refinedPrompt,
    freeTextDirty:   false,
    structured:      { ...row.structured, narrationLines: [...row.structured.narrationLines] },
    structuredDirty: false,
    activeVersion:   'refined',
    editMode:        'freetext',
    isExpanded:      row.rowIndex === 0,   // first card open by default
    isRefining:      false,
  }
}

function getFinalPrompt(row: RefinedRow, state: RowEditState): string {
  if (state.activeVersion === 'freetext')   return state.freeText
  if (state.activeVersion === 'structured') return structuredToPrompt(state.structured)
  return row.refinedPrompt
}

// ── Colours ────────────────────────────────────────────────────────────────────
const C = {
  warning:   '#FF9F0A',
  mythology: '#BF5AF2',
  accent:    'var(--accent)',
  error:     'var(--error)',
  text:      'var(--text)',
  text2:     'var(--text2)',
  text3:     'var(--text3)',
  border:    'var(--border)',
  border2:   'var(--border2)',
  surface:   'var(--surface)',
  surface2:  'var(--surface2)',
}

// ── Main component ─────────────────────────────────────────────────────────────
export function RefinementOverlay({ jobId, rows, refinerMode, onApprove, onReject }: Props) {
  const [states, setStates] = useState<RowEditState[]>(() => rows.map(initRowState))
  const [approving, setApproving] = useState(false)

  function updateState(idx: number, patch: Partial<RowEditState>) {
    setStates(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s))
  }

  // ── Free text edit ─────────────────────────────────────────────────────────
  function onFreeTextChange(idx: number, value: string) {
    updateState(idx, {
      freeText:      value,
      freeTextDirty: true,
      activeVersion: 'freetext',
    })
  }

  // ── Structured edit ────────────────────────────────────────────────────────
  function onStructuredChange(idx: number, field: keyof StructuredFields, value: string | string[]) {
    setStates(prev => prev.map((s, i) => {
      if (i !== idx) return s
      return {
        ...s,
        structured:      { ...s.structured, [field]: value },
        structuredDirty: true,
        activeVersion:   'structured',
      }
    }))
  }

  function onNarrationLineChange(idx: number, lineIdx: number, value: string) {
    setStates(prev => prev.map((s, i) => {
      if (i !== idx) return s
      const lines = [...s.structured.narrationLines]
      lines[lineIdx] = value
      return {
        ...s,
        structured:      { ...s.structured, narrationLines: lines },
        structuredDirty: true,
        activeVersion:   'structured',
      }
    }))
  }

  function addNarrationLine(idx: number) {
    setStates(prev => prev.map((s, i) => {
      if (i !== idx) return s
      const lines = [...s.structured.narrationLines, '']
      return { ...s, structured: { ...s.structured, narrationLines: lines }, structuredDirty: true, activeVersion: 'structured' }
    }))
  }

  function removeNarrationLine(idx: number, lineIdx: number) {
    setStates(prev => prev.map((s, i) => {
      if (i !== idx) return s
      const lines = s.structured.narrationLines.filter((_, li) => li !== lineIdx)
      return { ...s, structured: { ...s.structured, narrationLines: lines }, structuredDirty: true, activeVersion: 'structured' }
    }))
  }

  // ── Sync structured → free text ───────────────────────────────────────────
  function handleSyncToFreeText(idx: number) {
    const state = states[idx]
    const synced = structuredToPrompt(state.structured)
    setStates(prev => prev.map((s, i) => i !== idx ? s : {
      ...s,
      freeText:      synced,
      freeTextDirty: true,
      editMode:      'freetext',   // switch to freetext so user sees the result
      activeVersion: 'freetext',   // now sending freetext (which matches structured)
    }))
  }

  // ── Refine Again ───────────────────────────────────────────────────────────
  const handleRefineAgain = useCallback(async (idx: number) => {
    updateState(idx, { isRefining: true })
    try {
      const refreshed = await refineRowAgain(jobId, idx)
      setStates(prev => prev.map((s, i) => {
        if (i !== idx) return s
        // Reset BOTH edit states to new LLM output
        return {
          ...s,
          freeText:        refreshed.refinedPrompt,
          freeTextDirty:   false,
          structured:      { ...refreshed.structured, narrationLines: [...refreshed.structured.narrationLines] },
          structuredDirty: false,
          activeVersion:   'refined',
          isRefining:      false,
        }
      }))
    } catch {
      updateState(idx, { isRefining: false })
    }
  }, [jobId])

  // ── Approve ────────────────────────────────────────────────────────────────
  async function handleApprove() {
    setApproving(true)
    const approvedRows = rows.map((row, idx) => ({
      rowIndex:    row.rowIndex,
      finalPrompt: getFinalPrompt(row, states[idx]),
    }))
    onApprove(approvedRows)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'var(--bg)', display: 'flex', flexDirection: 'column',
    }}>
      {/* ── Header ── */}
      <div style={{
        padding: '16px 24px', borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: 'var(--bg)', flexShrink: 0,
      }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: C.text }}>
            Review Refined Prompts
          </h2>
          <p style={{ fontSize: 12, color: C.text2, margin: '2px 0 0' }}>
            {rows.length} row{rows.length !== 1 ? 's' : ''} refined
            {refinerMode === 2 ? ' · Mode 2 (lightweight)' : ' · Mode 1 (standard)'}
            · Approve to begin generation
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onReject} style={btnStyle('ghost')}>
            ✕ Reject — back to upload
          </button>
          <button
            onClick={handleApprove}
            disabled={approving}
            style={btnStyle('primary', approving)}
          >
            {approving ? 'Starting…' : '✓ Approve & Generate'}
          </button>
        </div>
      </div>

      {/* ── Scrollable cards ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {rows.map((row, idx) => (
            <RowCard
              key={row.rowIndex}
              row={row}
              state={states[idx]}
              onToggleExpand={() => updateState(idx, { isExpanded: !states[idx].isExpanded })}
              onEditModeToggle={(m) => updateState(idx, { editMode: m })}
              onFreeTextChange={(v) => onFreeTextChange(idx, v)}
              onStructuredChange={(f, v) => onStructuredChange(idx, f, v)}
              onNarrationLineChange={(li, v) => onNarrationLineChange(idx, li, v)}
              onAddNarrationLine={() => addNarrationLine(idx)}
              onRemoveNarrationLine={(li) => removeNarrationLine(idx, li)}
              onRefineAgain={() => handleRefineAgain(idx)}
            onSyncToFreeText={() => handleSyncToFreeText(idx)}
            />
          ))}
        </div>
      </div>

      {/* ── Footer summary ── */}
      <div style={{
        padding: '12px 24px', borderTop: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 20, flexShrink: 0,
        fontSize: 12, color: C.text2,
      }}>
        <span>
          {states.filter(s => s.freeTextDirty || s.structuredDirty).length} row(s) edited
        </span>
        <span>
          {rows.filter(r => r.mythologyDetected).length > 0 &&
            `🔮 ${rows.filter(r => r.mythologyDetected).length} mythology style lock(s) applied`}
        </span>
        <span style={{ marginLeft: 'auto' }}>
          Total duration: {rows.reduce((sum, r) => sum + r.duration, 0)}s
        </span>
      </div>
    </div>
  )
}

// ── Row Card ───────────────────────────────────────────────────────────────────
interface CardProps {
  row:                   RefinedRow
  state:                 RowEditState
  onToggleExpand:        () => void
  onEditModeToggle:      (m: 'freetext' | 'structured') => void
  onFreeTextChange:      (v: string) => void
  onStructuredChange:    (f: keyof StructuredFields, v: string | string[]) => void
  onNarrationLineChange: (li: number, v: string) => void
  onAddNarrationLine:    () => void
  onRemoveNarrationLine: (li: number) => void
  onRefineAgain:         () => void
  onSyncToFreeText:      () => void
}

function RowCard({
  row, state,
  onToggleExpand, onEditModeToggle, onFreeTextChange,
  onStructuredChange, onNarrationLineChange, onAddNarrationLine,
  onRemoveNarrationLine, onRefineAgain, onSyncToFreeText,
}: CardProps) {
  const hasEdits    = state.freeTextDirty || state.structuredDirty
  const totalDurS   = row.clips.length > 0 ? row.clips[row.clips.length - 1].endS : row.duration
  const durationStr = row.clips.length > 0
    ? `${row.clips.length} clip${row.clips.length !== 1 ? 's' : ''} · ${totalDurS}s total`
    : `${row.duration}s`

  return (
    <div style={{
      border: `1px solid ${hasEdits ? C.accent : C.border2}`,
      borderRadius: 12,
      background: C.surface,
      overflow: 'hidden',
      transition: 'border-color .15s',
    }}>
      {/* Card header */}
      <button
        onClick={onToggleExpand}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 16px', background: 'none', border: 'none',
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontSize: 11, fontWeight: 600, padding: '2px 8px',
            borderRadius: 20, background: C.surface2, color: C.text2,
          }}>
            Row {row.rowNumber}
          </span>
          {row.mythologyDetected && (
            <span style={{ fontSize: 11, color: C.mythology }}>🔮 mythology</span>
          )}
          {hasEdits && (
            <span style={{ fontSize: 11, color: C.accent }}>✎ edited</span>
          )}
          {row.warnings.length > 0 && (
            <span style={{ fontSize: 11, color: C.warning }}>
              ⚠ {row.warnings.length} warning{row.warnings.length > 1 ? 's' : ''}
            </span>
          )}
          <span style={{ fontSize: 12, color: C.text2, maxWidth: 360,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {row.originalPrompt.slice(0, 80)}{row.originalPrompt.length > 80 ? '…' : ''}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, color: C.text3 }}>{durationStr}</span>
          <span style={{ fontSize: 14, color: C.text3 }}>{state.isExpanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {state.isExpanded && (
        <div style={{ padding: '0 16px 16px', borderTop: `1px solid ${C.border}` }}>
          {/* Clip timestamps */}
          {row.clips.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12, marginBottom: 14 }}>
              {row.clips.map(clip => (
                <span key={clip.clip} style={{
                  fontSize: 10, fontWeight: 500, padding: '3px 8px',
                  borderRadius: 6, background: C.surface2,
                  border: `1px solid ${C.border}`, color: C.text3,
                }}>
                  {clip.label}
                </span>
              ))}
            </div>
          )}

          {/* Warnings */}
          {row.warnings.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              {row.warnings.map((w, i) => (
                <div key={i} style={{
                  fontSize: 11, color: C.warning, padding: '5px 10px',
                  background: `${C.warning}15`, borderRadius: 6,
                  marginBottom: 4,
                }}>
                  ⚠ {w}
                </div>
              ))}
            </div>
          )}

          {/* Edit mode toggle + Refine Again */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{
              display: 'flex', borderRadius: 20, overflow: 'hidden',
              border: `1px solid ${C.border}`,
            }}>
              {(['freetext', 'structured'] as const).map(m => (
                <button
                  key={m}
                  onClick={() => onEditModeToggle(m)}
                  style={{
                    padding: '4px 14px', fontSize: 12, fontWeight: 500,
                    background: state.editMode === m ? C.text : 'none',
                    color: state.editMode === m ? 'var(--bg)' : C.text2,
                    border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                    transition: 'all .15s',
                  }}
                >
                  {m === 'freetext' ? 'Free Text' : 'Structured'}
                  {m === 'freetext' && state.freeTextDirty && ' ✎'}
                  {m === 'structured' && state.structuredDirty && ' ✎'}
                </button>
              ))}
            </div>
            <button
              onClick={onRefineAgain}
              disabled={state.isRefining}
              style={{
                fontSize: 11, padding: '4px 12px',
                borderRadius: 20, border: `1px solid ${C.border}`,
                background: 'none', color: C.text2,
                cursor: state.isRefining ? 'not-allowed' : 'pointer',
                opacity: state.isRefining ? 0.5 : 1, fontFamily: 'inherit',
              }}
            >
              {state.isRefining ? 'Refining…' : '↻ Refine Again'}
            </button>
          </div>

          {/* Active version banner — prominent, always visible */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '7px 12px', borderRadius: 8, marginBottom: 10,
            background: state.activeVersion === 'refined'
              ? `${C.border}40`
              : state.activeVersion === 'structured' && state.editMode === 'freetext'
              ? '#FF9F0A20'
              : `${C.accent}18`,
            border: `1px solid ${
              state.activeVersion === 'refined'
                ? C.border
                : state.activeVersion === 'structured' && state.editMode === 'freetext'
                ? '#FF9F0A'
                : C.accent
            }`,
          }}>
            <span style={{
              fontSize: 11, fontWeight: 600,
              color: state.activeVersion === 'refined'
                ? C.text2
                : state.activeVersion === 'structured' && state.editMode === 'freetext'
                ? '#FF9F0A'
                : C.accent,
            }}>
              {state.activeVersion === 'refined'
                ? '→ Sending: LLM-refined version (no edits made)'
                : state.activeVersion === 'freetext'
                ? '→ Sending: your free text edits'
                : state.editMode === 'freetext'
                ? '⚠ Sending: your STRUCTURED edits (not what you see here — switch to Structured tab to review)'
                : '→ Sending: your structured edits'}
            </span>
            {/* Sync button: push structured → freetext so user can see the combined result */}
            {state.activeVersion === 'structured' && state.editMode === 'freetext' && (
              <button
                onClick={() => onSyncToFreeText()}
                style={{
                  fontSize: 10, padding: '3px 10px', borderRadius: 10,
                  border: '1px solid #FF9F0A', background: 'none',
                  color: '#FF9F0A', cursor: 'pointer', fontFamily: 'inherit',
                  fontWeight: 500, whiteSpace: 'nowrap',
                }}
              >
                Sync to free text
              </button>
            )}
          </div>

          {/* ── Free text editor ── */}
          {state.editMode === 'freetext' && (
            <textarea
              value={state.freeText}
              onChange={e => onFreeTextChange(e.target.value)}
              rows={8}
              style={{
                width: '100%', background: C.surface2,
                border: `1px solid ${state.freeTextDirty ? C.accent : C.border}`,
                borderRadius: 8, padding: '10px 12px',
                fontSize: 13, color: C.text, fontFamily: 'inherit',
                resize: 'vertical', outline: 'none', boxSizing: 'border-box',
                lineHeight: 1.6,
              }}
            />
          )}

          {/* ── Structured editor ── */}
          {state.editMode === 'structured' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(
                [
                  ['scene',      'Scene'],
                  ['characters', 'Characters'],
                  ['camera',     'Camera'],
                  ['lighting',   'Lighting'],
                  ['mythologyNotes', 'Mythology Style Notes'],
                ] as [keyof StructuredFields, string][]
              ).map(([field, label]) => (
                <div key={field}>
                  <label style={labelStyle}>{label}</label>
                  <textarea
                    value={state.structured[field] as string}
                    onChange={e => onStructuredChange(field, e.target.value)}
                    rows={field === 'mythologyNotes' ? 4 : 2}
                    style={{
                      width: '100%', background: C.surface2,
                      border: `1px solid ${state.structuredDirty ? C.accent : C.border}`,
                      borderRadius: 6, padding: '7px 10px',
                      fontSize: 12, color: C.text, fontFamily: 'inherit',
                      resize: 'vertical', outline: 'none', boxSizing: 'border-box',
                    }}
                  />
                </div>
              ))}

              {/* Narration lines */}
              <div>
                <label style={labelStyle}>Narration Lines</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {state.structured.narrationLines.map((line, li) => (
                    <div key={li} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                      <span style={{ fontSize: 10, color: C.text3, paddingTop: 8, minWidth: 20 }}>
                        {li + 1}.
                      </span>
                      <textarea
                        value={line}
                        onChange={e => onNarrationLineChange(li, e.target.value)}
                        rows={2}
                        style={{
                          flex: 1, background: C.surface2,
                          border: `1px solid ${state.structuredDirty ? C.accent : C.border}`,
                          borderRadius: 6, padding: '7px 10px',
                          fontSize: 12, color: C.text, fontFamily: 'inherit',
                          resize: 'vertical', outline: 'none', boxSizing: 'border-box',
                        }}
                      />
                      <button
                        onClick={() => onRemoveNarrationLine(li)}
                        style={{
                          padding: '4px 8px', fontSize: 11, borderRadius: 6,
                          border: `1px solid ${C.border}`, background: 'none',
                          color: C.error, cursor: 'pointer', fontFamily: 'inherit',
                          marginTop: 4,
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                  <button
                    onClick={onAddNarrationLine}
                    style={{
                      fontSize: 11, padding: '5px 12px', borderRadius: 6,
                      border: `1px solid ${C.border}`, background: 'none',
                      color: C.text2, cursor: 'pointer', fontFamily: 'inherit',
                      alignSelf: 'flex-start',
                    }}
                  >
                    + Add line
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Mythology lock info */}
          {row.mythologyDetected && (
            <div style={{
              marginTop: 12, fontSize: 11, color: C.mythology,
              padding: '6px 10px', background: `${C.mythology}10`,
              borderRadius: 6, borderLeft: `3px solid ${C.mythology}`,
            }}>
              🔮 Indian mythology visual style lock automatically applied.
              Edit in Mythology Style Notes (structured mode) if needed.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Style helpers ──────────────────────────────────────────────────────────────
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 11, fontWeight: 500,
  color: 'var(--text2)', marginBottom: 4,
}

function btnStyle(variant: 'primary' | 'ghost', disabled = false): React.CSSProperties {
  const base: React.CSSProperties = {
    fontSize: 13, fontWeight: 500, padding: '8px 18px',
    borderRadius: 'var(--pill)', cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit', opacity: disabled ? 0.5 : 1,
    transition: 'all .15s', border: '1px solid var(--border)',
  }
  if (variant === 'primary') return { ...base, background: 'var(--text)', color: 'var(--bg)', border: 'none' }
  return { ...base, background: 'none', color: 'var(--text2)' }
}