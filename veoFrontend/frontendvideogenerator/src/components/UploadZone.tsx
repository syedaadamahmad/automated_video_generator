// src/components/UploadZone.tsx
'use client'
import { useRef, useState } from 'react'
import { Tooltip } from './Tooltip'

interface Props {
  onFile: (file: File) => void
  disabled?: boolean
}

export function UploadZone({ onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handle(file: File | null) {
    if (!file) return
    if (!file.name.match(/\.(xlsx|xls)$/i)) return
    onFile(file)
  }

  return (
    <div
      className={`upload-zone ${dragging ? 'drag-over' : ''}`}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => {
        e.preventDefault()
        setDragging(false)
        handle(e.dataTransfer.files[0] ?? null)
      }}
      style={{ opacity: disabled ? 0.5 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}
    >
      <div style={{ fontSize: 28, marginBottom: 10, color: 'var(--text3)' }}>↑</div>
      <div style={{ fontWeight: 500, fontSize: 15, color: 'var(--text)', marginBottom: 4 }}>
        Drop your Excel file here
      </div>
      <div style={{ fontSize: 13, color: 'var(--text2)' }}>
        or click to browse — .xlsx or .xls
      </div>
      <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 8 }}>
        Columns: prompt, duration, aspect_ratio, task_type, priority
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.xls"
        style={{ display: 'none' }}
        onChange={e => handle(e.target.files?.[0] ?? null)}
      />
    </div>
  )
}

export function SectionLabel({
  children,
  tooltip,
}: {
  children: React.ReactNode
  tooltip?: string
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        fontSize: 22,
        fontWeight: 600,
        letterSpacing: '-0.025em',
        color: 'var(--text)',
        marginBottom: '0.3rem',
      }}
    >
      {children}
      {tooltip && <Tooltip text={tooltip} />}
    </div>
  )
}
