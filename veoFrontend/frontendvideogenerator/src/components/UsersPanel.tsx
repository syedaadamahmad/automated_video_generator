// src/components/UsersPanel.tsx
// Admin-only user management panel.
// Lists all users, allows creating, editing role/name, resetting password,
// and deleting users. Self-deletion is blocked by the backend.
'use client'
import { useState } from 'react'
import useSWR from 'swr'
import { Tooltip } from './Tooltip'

interface AppUser {
  id:         string
  email:      string
  name:        string
  role:        'admin' | 'editor' | 'viewer'
  created_at:  string
}

async function fetchUsers(): Promise<AppUser[]> {
  const res = await fetch('/api/proxy/api/users')
  if (!res.ok) throw new Error('Failed to fetch users')
  const data = await res.json()
  return data.users
}

const ROLE_COLORS: Record<string, string> = {
  admin:  '#0071E3',
  editor: '#34C759',
  viewer: '#8E8E93',
}

export function UsersPanel() {
  const { data: users, mutate, error } = useSWR<AppUser[]>('users', fetchUsers)

  const [showCreate, setShowCreate] = useState(false)
  const [toast, setToast]           = useState<{ msg: string; ok: boolean } | null>(null)

  // Create form state
  const [newEmail, setNewEmail]   = useState('')
  const [newName, setNewName]     = useState('')
  const [newPass, setNewPass]     = useState('')
  const [newRole, setNewRole]     = useState<'admin' | 'editor' | 'viewer'>('editor')
  const [creating, setCreating]   = useState(false)

  function showToast(msg: string, ok = true) {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 3000)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      const res = await fetch('/api/proxy/api/users', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email: newEmail, password: newPass, name: newName, role: newRole }),
      })
      if (!res.ok) {
        const err = await res.json()
        showToast(err.detail ?? 'Create failed', false)
      } else {
        showToast(`Created ${newEmail}`)
        setNewEmail(''); setNewName(''); setNewPass(''); setNewRole('editor')
        setShowCreate(false)
        mutate()
      }
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(email: string) {
    if (!confirm(`Delete ${email}? This cannot be undone.`)) return
    const res = await fetch(`/api/proxy/api/users/${encodeURIComponent(email)}`, { method: 'DELETE' })
    if (res.ok) { showToast(`Deleted ${email}`); mutate() }
    else { const e = await res.json(); showToast(e.detail ?? 'Delete failed', false) }
  }

  async function handleRoleChange(email: string, role: string) {
    const res = await fetch(`/api/proxy/api/users/${encodeURIComponent(email)}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ role }),
    })
    if (res.ok) { showToast('Role updated'); mutate() }
    else { const e = await res.json(); showToast(e.detail ?? 'Update failed', false) }
  }

  if (error) return (
    <div className="alert alert-error">Failed to load users — is veo_main.py running?</div>
  )

  return (
    <div style={{ position: 'relative' }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          background: toast.ok ? 'var(--text)' : 'var(--error)',
          color: 'var(--bg)', fontSize: 13, fontWeight: 500,
          padding: '7px 18px', borderRadius: 'var(--pill)', zIndex: 100,
          boxShadow: '0 4px 20px rgba(0,0,0,.2)', whiteSpace: 'nowrap',
        }}>
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <h2 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.025em', color: 'var(--text)' }}>
            Users
          </h2>
          <Tooltip text="Manage who can access Veo Studio. Admin can create, edit, and delete accounts. Users only see their own generated videos." />
        </div>
        <button
          onClick={() => setShowCreate(s => !s)}
          style={{
            fontSize: 13, fontWeight: 500, padding: '6px 16px',
            borderRadius: 'var(--pill)', border: '1px solid var(--border)',
            background: showCreate ? 'var(--text)' : 'none',
            color: showCreate ? 'var(--bg)' : 'var(--text)',
            cursor: 'pointer', fontFamily: 'inherit', transition: 'all .15s',
          }}
        >
          {showCreate ? '✕ Cancel' : '+ New User'}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <form onSubmit={handleCreate} style={{
          background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: 'var(--radius-lg)', padding: '1.25rem 1.5rem',
          marginBottom: '1.25rem',
        }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <label style={labelStyle}>Email</label>
              <input required type="email" value={newEmail}
                onChange={e => setNewEmail(e.target.value)}
                placeholder="user@example.com" style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Name</label>
              <input required value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="Full name" style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Password</label>
              <input required type="password" value={newPass}
                onChange={e => setNewPass(e.target.value)}
                placeholder="••••••••" style={inputStyle} minLength={6} />
            </div>
            <div>
              <label style={labelStyle}>Role</label>
              <select value={newRole} onChange={e => setNewRole(e.target.value as typeof newRole)}
                style={{ ...inputStyle, cursor: 'pointer' }}>
                <option value="editor">Editor — generate &amp; rerun</option>
                <option value="viewer">Viewer — view only</option>
                <option value="admin">Admin — full access</option>
              </select>
            </div>
          </div>
          <button type="submit" disabled={creating} style={{
            background: 'var(--text)', color: 'var(--bg)', border: 'none',
            borderRadius: 'var(--pill)', padding: '8px 20px',
            fontSize: 13, fontWeight: 600, cursor: creating ? 'not-allowed' : 'pointer',
            opacity: creating ? 0.5 : 1, fontFamily: 'inherit',
          }}>
            {creating ? 'Creating…' : 'Create User'}
          </button>
        </form>
      )}

      {/* User list */}
      {!users ? (
        <div style={{ color: 'var(--text2)', fontSize: 13 }}>Loading…</div>
      ) : (
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: 'var(--radius-lg)', overflow: 'hidden',
        }}>
          <table className="veo-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>
                  Role
                  <Tooltip text="Admin = full access. Editor = generate, rerun, reject. Viewer = view videos only." />
                </th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => (
                <tr key={user.email}>
                  <td style={{ fontWeight: 500 }}>{user.name}</td>
                  <td style={{ fontSize: 13, color: 'var(--text2)' }}>{user.email}</td>
                  <td>
                    <select
                      value={user.role}
                      onChange={e => handleRoleChange(user.email, e.target.value)}
                      style={{
                        fontSize: 11, fontWeight: 500,
                        padding: '3px 8px', borderRadius: 20,
                        border: `1px solid ${ROLE_COLORS[user.role]}40`,
                        color: ROLE_COLORS[user.role],
                        background: `${ROLE_COLORS[user.role]}10`,
                        cursor: 'pointer', fontFamily: 'inherit',
                        appearance: 'none',
                      }}
                    >
                      <option value="admin">admin</option>
                      <option value="editor">editor</option>
                      <option value="viewer">viewer</option>
                    </select>
                  </td>
                  <td style={{ fontSize: 11, color: 'var(--text3)' }}>
                    {new Date(user.created_at).toLocaleDateString()}
                  </td>
                  <td>
                    <button
                      onClick={() => handleDelete(user.email)}
                      style={{
                        fontSize: 11, padding: '3px 10px',
                        borderRadius: 'var(--pill)',
                        border: '1px solid var(--error)',
                        color: 'var(--error)', background: 'none',
                        cursor: 'pointer', fontFamily: 'inherit',
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 11, fontWeight: 500,
  color: 'var(--text2)', marginBottom: 5,
}
const inputStyle: React.CSSProperties = {
  width: '100%', background: 'var(--surface2)',
  border: '1px solid var(--border)', borderRadius: 8,
  padding: '8px 10px', fontSize: 13, color: 'var(--text)',
  fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
}