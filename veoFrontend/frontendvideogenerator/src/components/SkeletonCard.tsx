// src/components/SkeletonCard.tsx
'use client'

export function SkeletonCard() {
  return (
    <div className="video-card">
      {/* 9:16 aspect ratio video area */}
      <div
        className="skeleton"
        style={{
          width: '100%',
          paddingTop: '177.78%',
          borderRadius: '16px 16px 0 0',
        }}
      />
      <div style={{ padding: '12px 14px 14px' }}>
        <div className="skeleton" style={{ height: 10, width: '65%', marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 10, width: '40%', marginBottom: 14 }} />
        <div
          className="skeleton"
          style={{ height: 32, borderRadius: 'var(--pill)', width: '100%' }}
        />
      </div>
    </div>
  )
}
