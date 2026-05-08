// src/components/Tooltip.tsx
'use client'
interface Props {
  text: string
  children?: React.ReactNode
}

export function Tooltip({ text, children }: Props) {
  return (
    <span className="tooltip-wrap" style={{ cursor: 'default' }}>
      {children ?? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 16,
            height: 16,
            borderRadius: '50%',
            border: '1px solid var(--text3)',
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--text3)',
            marginLeft: 5,
            userSelect: 'none',
            flexShrink: 0,
          }}
        >
          ?
        </span>
      )}
      <span className="tooltip-box">{text}</span>
    </span>
  )
}
