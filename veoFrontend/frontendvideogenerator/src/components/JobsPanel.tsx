// src/components/JobsPanel.tsx
'use client'
import { useState } from 'react'
import useSWR from 'swr'
import { listJobs } from '@/lib/api'
import type { JobListItem } from '@/types'
import { StatusPill } from './StatusPill'
import { Tooltip } from './Tooltip'

const VEO_API = 'http://localhost:8100'

export function JobsPanel() {
  const { data: jobs } = useSWR<JobListItem[]>('jobs-list', listJobs, { refreshInterval: 10000 })
  const [open, setOpen] = useState(false)

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border2)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
      }}
    >
      {/* Header toggle */}
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
        }}
      >
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 14,
            fontWeight: 500,
            color: 'var(--text)',
          }}
        >
          📋 Jobs
          <Tooltip text="All generation jobs for your account. Admins see all users' jobs." />
          {jobs && (
            <span style={{ fontSize: 11, color: 'var(--text3)', marginLeft: 2 }}>
              ({jobs.length})
            </span>
          )}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--border2)' }}>
          {!jobs || jobs.length === 0 ? (
            <div style={{ padding: '1rem 1.25rem', fontSize: 13, color: 'var(--text2)' }}>
              No jobs yet.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="veo-table">
                <thead>
                  <tr>
                    <th>Job ID</th>
                    <th>File</th>
                    <th>Status</th>
                    <th>Prompts</th>
                    <th>Created</th>
                    <th>Video</th>
                  </tr>
                </thead>
                <tbody>
                  {([...(jobs ?? [])]).slice().reverse().map((job: JobListItem) => (
                    <tr key={job.job_id}>
                      <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text2)' }}>
                        {job.job_id}
                      </td>
                      <td style={{ fontSize: 12 }}>{job.original_filename}</td>
                      <td><StatusPill status={job.status} /></td>
                      <td style={{ fontSize: 12 }}>
                        {job.completed_prompts}/{job.total_prompts}
                      </td>
                      <td style={{ fontSize: 11, color: 'var(--text2)', whiteSpace: 'nowrap' }}>
                        {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                      </td>
                      <td>
                        <a
                          href={`${VEO_API}/api/jobs/${job.job_id}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
                        >
                          ↗ JSON
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}