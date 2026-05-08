// src/components/MetricsPanel.tsx
'use client'
import { useState } from 'react'
import useSWR from 'swr'
import { fetchMetrics } from '@/lib/api'
import { Tooltip } from './Tooltip'
import type { Metrics } from '@/types'

function Metric({ label, value, tooltip }: { label: string; value: string | number; tooltip?: string }) {
  return (
    <div
      style={{
        background: 'var(--surface2)',
        border: '1px solid var(--border2)',
        borderRadius: 10,
        padding: '10px 14px',
      }}
    >
      <div
        style={{
          fontSize: 20,
          fontWeight: 600,
          letterSpacing: '-0.03em',
          color: 'var(--text)',
          lineHeight: 1,
          marginBottom: 4,
        }}
      >
        {value}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text2)' }}>{label}</span>
        {tooltip && <Tooltip text={tooltip} />}
      </div>
    </div>
  )
}

export function MetricsPanel() {
  const [open, setOpen] = useState(false)
  const { data: m } = useSWR<Metrics>(
    open ? 'metrics' : null,
    fetchMetrics,
    { refreshInterval: 5000 },
  )

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border2)',
        borderRadius: 'var(--radius-lg)',
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
          📊 Metrics
          <Tooltip text="Live stats for the current server session. Resets when veo_main.py restarts." />
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--border2)', padding: '1rem 1.25rem' }}>
          {!m ? (
            <div style={{ fontSize: 13, color: 'var(--text2)' }}>Loading…</div>
          ) : (
            <>
              {/* Veo */}
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 8 }}>Veo API</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, marginBottom: 16 }}>
                <Metric label="Clips generated" value={m.veo.clips_generated} />
                <Metric label="Avg clip time" value={`${m.veo.avg_clip_time_s}s`} tooltip="Average time per clip from submit to download." />
                <Metric label="429 rate limits" value={m.veo.rate_limit_hits} tooltip="Number of 429 RESOURCE_EXHAUSTED errors. Free tier: 50 requests/day." />
                <Metric label="Session cost" value={`₹${m.cost_estimate.inr.toFixed(2)}`} tooltip="Estimated cost for this server session based on successful clips." />
              </div>

              {/* Rate limit health */}
              {m.veo.submissions > 0 && (
                <div
                  className={`alert ${m.veo.rate_limit_pct === 0 ? 'alert-info' : m.veo.rate_limit_pct < 20 ? 'alert-warn' : 'alert-error'}`}
                  style={{ marginBottom: 16, fontSize: 12 }}
                >
                  {m.veo.rate_limit_pct === 0
                    ? '✅  No rate limit hits this session'
                    : m.veo.rate_limit_pct < 20
                    ? `⚠️  ${m.veo.rate_limit_pct}% submissions hit rate limits`
                    : `🔴  ${m.veo.rate_limit_pct}% rate limit hit rate — pace your submissions`}
                </div>
              )}

              {/* Decomposer */}
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 8 }}>
                Decomposer
                <Tooltip text="3-tier fallback: Nova 2 Lite → DeepSeek R1 → Deterministic. DeepSeek and Deterministic counts are fallback indicators." />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, marginBottom: 16 }}>
                <Metric label="Nova 2 Lite" value={m.decomposer.nova_calls} />
                <Metric label="DeepSeek R1" value={m.decomposer.deepseek_calls} tooltip="Called when Nova 2 Lite fails. Non-zero = fallback triggered." />
                <Metric label="Deterministic" value={m.decomposer.deterministic} tooltip="LLM-free fallback. Called when both LLMs fail." />
                <Metric label="Input tokens" value={m.decomposer.input_tokens.toLocaleString()} />
              </div>

              {/* S3 */}
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 8 }}>S3</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                <Metric label="Uploads OK" value={m.s3.uploads_ok} />
                <Metric label="Uploads failed" value={m.s3.uploads_fail} tooltip="Failed S3 uploads. Video still accessible locally via FastAPI." />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
