// src/components/StatusPill.tsx
'use client'
import type { JobStatus, PromptStatus } from '@/types'

const MAP: Record<string, { label: string; cls: string }> = {
  completed:  { label: 'done',       cls: 'pill-done'    },
  partial:    { label: 'partial',    cls: 'pill-partial'  },
  processing: { label: 'generating', cls: 'pill-run'      },
  pending:    { label: 'pending',    cls: 'pill-pending'  },
  failed:     { label: 'failed',     cls: 'pill-fail'     },
}

export function StatusPill({ status }: { status: JobStatus | PromptStatus | string }) {
  const { label, cls } = MAP[status] ?? { label: status, cls: 'pill-pending' }
  return (
    <span
      className={cls}
      style={{
        display: 'inline-block',
        fontSize: 11,
        fontWeight: 500,
        padding: '2px 8px',
        borderRadius: 20,
      }}
    >
      {label}
    </span>
  )
}
