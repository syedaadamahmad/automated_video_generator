// src/components/VideoCard.tsx
'use client'
import { useState } from 'react'
import { StatusPill } from './StatusPill'
import { localVideoSrc, approveVideo, rerunPrompt } from '@/lib/api'
import type { Prompt } from '@/types'
import type { Role } from '@/types'
import { hasPermission } from '@/lib/permissions'

const AR_RATIO: Record<string, string> = {
  '9:16': '9/16',
  '16:9': '16/9',
  '1:1':  '1/1',
  '4:3':  '4/3',
}

interface Props {
  prompt:   Prompt
  jobId:    string
  index:    number
  role:     Role
  onReject: (jobId: string, index: number) => void
  onRerun:  () => void
}

export function VideoCard({ prompt, jobId, index, role, onReject, onRerun }: Props) {
  const [approving, setApproving] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [toast, setToast]         = useState<string | null>(null)

  const ar       = prompt.aspect_ratio ?? '9:16'
  const arCss    = AR_RATIO[ar] ?? '9/16'
  const srcUrl   = localVideoSrc(prompt.local_video_url, prompt.video_url)
  const shortPr  = (prompt.prompt_text ?? '').slice(0, 80)
  const clips    = prompt.clips_count ?? 1
  const dur      = prompt.duration_seconds ?? prompt.duration

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  async function handleApprove() {
    setApproving(true)
    try {
      await approveVideo(jobId, index)
      showToast('Added to YouTube queue ✓')
    } catch (err: unknown) {
      showToast('Approve failed: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setApproving(false)
    }
  }

  async function handleRerun() {
    setRerunning(true)
    try {
      await rerunPrompt(jobId, index)
      showToast('Rerunning…')
      onRerun()
    } catch (err: unknown) {
      showToast('Rerun failed: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setRerunning(false)
    }
  }

  return (
    <div className="video-card" style={{ position: 'relative' }}>
      {/* Toast */}
      {toast && (
        <div
          style={{
            position: 'absolute',
            top: 10,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--text)',
            color: 'var(--bg)',
            fontSize: 12,
            fontWeight: 500,
            padding: '5px 12px',
            borderRadius: 'var(--pill)',
            zIndex: 10,
            whiteSpace: 'nowrap',
            boxShadow: '0 4px 16px rgba(0,0,0,.2)',
          }}
        >
          {toast}
        </div>
      )}

      {/* Video */}
      <div style={{ aspectRatio: arCss, background: '#000', overflow: 'hidden', borderRadius: '16px 16px 0 0' }}>
        {srcUrl ? (
          <video
            controls
            preload="metadata"
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          >
            <source src={srcUrl} type="video/mp4" />
          </video>
        ) : (
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#555',
              fontSize: 12,
            }}
          >
            Video unavailable
          </div>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '10px 14px 12px' }}>
        <div
          style={{
            fontSize: 12,
            color: 'var(--text2)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            marginBottom: 6,
          }}
          title={prompt.prompt_text}
        >
          {shortPr}{(prompt.prompt_text ?? '').length > 80 ? '…' : ''}
        </div>

        {/* Meta pills */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          <StatusPill status={prompt.status} />
          <span style={tagStyle}>{ar}</span>
          {clips > 0 && (
            <span style={tagStyle}>
              {clips} clip{clips !== 1 ? 's' : ''} · {dur}s
            </span>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
          {hasPermission(role, 'approve') && (
            <ActionBtn
              label="✓  Approve"
              loading={approving}
              onClick={handleApprove}
              primary
            />
          )}
          {hasPermission(role, 'rerun') && (
            <ActionBtn
              label="↺  Rerun"
              loading={rerunning}
              onClick={handleRerun}
            />
          )}
          {hasPermission(role, 'reject') && (
            <ActionBtn
              label="✕  Reject"
              loading={false}
              onClick={() => onReject(jobId, index)}
              danger
            />
          )}
        </div>
      </div>
    </div>
  )
}

const tagStyle: React.CSSProperties = {
  display: 'inline-block',
  fontSize: 11,
  fontWeight: 500,
  padding: '2px 7px',
  borderRadius: 20,
  border: '1px solid var(--border)',
  color: 'var(--text2)',
}

function ActionBtn({
  label, loading, onClick, primary, danger,
}: {
  label: string; loading: boolean; onClick: () => void; primary?: boolean; danger?: boolean
}) {
  const bg  = primary ? 'var(--text)' : 'none'
  const col = primary ? 'var(--bg)' : danger ? 'var(--error)' : 'var(--text2)'
  const brd = danger ? 'var(--error)' : 'var(--border)'

  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        fontSize: 12,
        fontWeight: 500,
        padding: '6px 4px',
        borderRadius: 'var(--pill)',
        border: `1px solid ${brd}`,
        background: bg,
        color: col,
        cursor: loading ? 'not-allowed' : 'pointer',
        opacity: loading ? 0.5 : 1,
        fontFamily: 'inherit',
        transition: 'opacity .15s, background .15s',
        whiteSpace: 'nowrap',
      }}
    >
      {loading ? '…' : label}
    </button>
  )
}