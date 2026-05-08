// src/app/login/page.tsx
'use client'
import { useState } from 'react'
import { signIn } from 'next-auth/react'
import { useRouter } from 'next/navigation'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    const result = await signIn('credentials', {
      email,
      password,
      redirect: false,
    })

    setLoading(false)

    if (result?.ok) {
      router.push('/generate')
      router.refresh()
    } else {
      setError('Incorrect email or password.')
    }
  }

  return (
    <div
      style={{
        minHeight: '100dvh',
        background: 'var(--bg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1.5rem',
      }}
    >
      <div style={{ width: '100%', maxWidth: 380 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          <div
            style={{
              fontSize: '1.75rem',
              fontWeight: 700,
              letterSpacing: '-0.035em',
              color: 'var(--text)',
            }}
          >
            Veo{' '}
            <span style={{ color: 'var(--text2)', fontWeight: 400 }}>Studio</span>
          </div>
          <div
            style={{
              fontSize: '0.9rem',
              color: 'var(--text2)',
              marginTop: '0.4rem',
            }}
          >
            Sign in to continue
          </div>
        </div>

        {/* Card */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-xl)',
            padding: '2rem',
          }}
        >
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: '1.1rem' }}>
              <label className="field-label">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoFocus
                className="field-input"
              />
            </div>

            <div style={{ marginBottom: '1.5rem' }}>
              <label className="field-label">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                className="field-input"
              />
            </div>

            {error && (
              <div
                style={{
                  fontSize: '0.83rem',
                  color: 'var(--error)',
                  marginBottom: '1rem',
                  textAlign: 'center',
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                background: 'var(--text)',
                color: 'var(--bg)',
                border: 'none',
                borderRadius: 'var(--pill)',
                padding: '0.72rem 1.5rem',
                fontSize: '0.9rem',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.5 : 1,
                transition: 'opacity .15s',
                fontFamily: 'inherit',
              }}
            >
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p
          style={{
            textAlign: 'center',
            fontSize: '0.75rem',
            color: 'var(--text3)',
            marginTop: '1.5rem',
          }}
        >
          Stub auth active — see <code>src/lib/auth-options.ts</code> to connect a real provider.
        </p>
      </div>

      <style>{`
        .field-label {
          display: block;
          font-size: 12px;
          font-weight: 500;
          color: var(--text2);
          margin-bottom: 6px;
          letter-spacing: .01em;
        }
        .field-input {
          width: 100%;
          background: var(--surface2);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 10px 12px;
          font-size: 14px;
          color: var(--text);
          font-family: inherit;
          outline: none;
          box-sizing: border-box;
          transition: border-color .15s;
        }
        .field-input:focus { border-color: var(--accent); }
        .field-input::placeholder { color: var(--text3); }
      `}</style>
    </div>
  )
}