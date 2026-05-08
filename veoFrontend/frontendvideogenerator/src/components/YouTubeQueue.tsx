// src/components/YouTubeQueue.tsx
'use client'
import { useState } from 'react'
import useSWR from 'swr'
import {
  fetchYouTubeStatus,
  fetchYouTubeQueue,
  updateQueueItem,
  removeFromQueue,
  triggerYouTubeUpload,
} from '@/lib/api'
import { StatusPill } from './StatusPill'
import { Tooltip } from './Tooltip'
import type { Role, YouTubeQueueItem, YouTubeStatus } from '@/types'
import { hasPermission } from '@/lib/permissions'

interface Props { role: Role }

export function YouTubeQueue({ role }: Props) {
  const { data: status } = useSWR<YouTubeStatus>('yt-status', fetchYouTubeStatus, { refreshInterval: 30000 })
  const { data: queue, mutate } = useSWR<YouTubeQueueItem[]>('yt-queue', fetchYouTubeQueue, { refreshInterval: 10000 })

  const [uploading, setUploading] = useState(false)
  const [toast, setToast]         = useState<string | null>(null)

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  async function handleUploadAll() {
    setUploading(true)
    try {
      const r = await triggerYouTubeUpload()
      showToast(r.status === 'ok' ? `Uploaded ${r.uploaded} video(s) ✓` : r.message ?? 'Upload failed')
    } finally {
      setUploading(false)
      mutate()
    }
  }

  if (!status?.configured) {
    return (
      <div className="alert alert-warn">
        ⚠️  YouTube not configured — add credentials to <code>veo.env</code>.
      </div>
    )
  }

  if (!status?.authenticated) {
    return (
      <div className="alert alert-info">
        ℹ️  Run the OAuth flow once to authenticate YouTube. See <code>veo_youtube.py</code>.
      </div>
    )
  }

  return (
    <div style={{ position: 'relative' }}>
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--text)',
            color: 'var(--bg)',
            fontSize: 13,
            fontWeight: 500,
            padding: '8px 18px',
            borderRadius: 'var(--pill)',
            zIndex: 100,
            boxShadow: '0 4px 20px rgba(0,0,0,.2)',
          }}
        >
          {toast}
        </div>
      )}

      {!queue || queue.length === 0 ? (
        <div style={{ fontSize: 13.5, color: 'var(--text2)', padding: '1rem 0' }}>
          Queue is empty. Approve a video card to add it here.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {queue.map((item: YouTubeQueueItem) => (
            <QueueItem
              key={item.queue_id ?? item.id}
              item={item}
              onUpdate={mutate}
              onRemove={mutate}
              showToast={showToast}
            />
          ))}
        </div>
      )}

      {hasPermission(role, 'approve') && queue && queue.length > 0 && (
        <div style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border2)' }}>
          <button
            onClick={handleUploadAll}
            disabled={uploading}
            style={{
              background: 'var(--text)',
              color: 'var(--bg)',
              border: 'none',
              borderRadius: 'var(--pill)',
              padding: '10px 24px',
              fontSize: 14,
              fontWeight: 600,
              cursor: uploading ? 'not-allowed' : 'pointer',
              opacity: uploading ? 0.5 : 1,
              fontFamily: 'inherit',
              transition: 'opacity .15s',
            }}
          >
            {uploading ? 'Uploading…' : `⬆  Upload all to YouTube (${queue.length})`}
          </button>
        </div>
      )}
    </div>
  )
}

function QueueItem({ item, onUpdate, onRemove, showToast }: {
  item: YouTubeQueueItem
  onUpdate: () => void
  onRemove: () => void
  showToast: (msg: string) => void
}) {
  const [open, setOpen]     = useState(false)
  const [title, setTitle]   = useState(item.title ?? '')
  const [desc, setDesc]     = useState(item.description ?? '')
  const [tags, setTags]     = useState((item.tags ?? []).join(', '))
  const [saving, setSaving] = useState(false)
  const qid = item.queue_id ?? item.id

  async function handleSave() {
    setSaving(true)
    try {
      await updateQueueItem(qid, { title, description: desc, tags: tags.split(',').map((t: string) => t.trim()).filter(Boolean) })
      showToast('Saved ✓')
      onUpdate()
    } catch { showToast('Save failed') }
    finally { setSaving(false) }
  }

  async function handleRemove() {
    try {
      await removeFromQueue(qid)
      onRemove()
    } catch { showToast('Remove failed') }
  }

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border2)',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
      }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontFamily: 'inherit',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--text)', textAlign: 'left', flex: 1 }}>
          {title || '(untitled)'}
        </span>
        <StatusPill status={item.status ?? 'approved'} />
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--border2)', padding: '1rem 1.25rem' }}>
          {item.local_path && (
            <video
              controls
              src={`/api/proxy${item.local_path}`}
              style={{ width: '100%', maxHeight: 200, objectFit: 'cover', borderRadius: 8, marginBottom: '1rem', background: '#000' }}
            />
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <label style={labelStyle}>Title</label>
              <input value={title} onChange={e => setTitle(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Tags (comma-separated)</label>
              <input value={tags} onChange={e => setTags(e.target.value)} style={inputStyle} placeholder="AI, education, students" />
            </div>
          </div>
          <div style={{ marginBottom: '1rem' }}>
            <label style={labelStyle}>Description</label>
            <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSave} disabled={saving} style={btnStyle}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button onClick={handleRemove} style={{ ...btnStyle, color: 'var(--error)', borderColor: 'var(--error)' }}>
              Remove
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 11, fontWeight: 500,
  color: 'var(--text2)', marginBottom: 5, letterSpacing: '.01em',
}
const inputStyle: React.CSSProperties = {
  width: '100%', background: 'var(--surface2)', border: '1px solid var(--border)',
  borderRadius: 8, padding: '8px 10px', fontSize: 13, color: 'var(--text)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}
const btnStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 500, padding: '6px 16px',
  borderRadius: 'var(--pill)', border: '1px solid var(--border)',
  background: 'none', color: 'var(--text)', cursor: 'pointer', fontFamily: 'inherit',
}