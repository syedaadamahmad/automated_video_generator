// src/lib/permissions.ts
import type { Role } from '@/types'

const PERMISSIONS: Record<Role, string[]> = {
  viewer: ['view_videos'],
  editor: ['view_videos', 'generate', 'rerun', 'reject', 'download'],
  admin:  ['view_videos', 'generate', 'rerun', 'reject', 'download',
           'approve', 'youtube_queue', 'view_metrics', 'view_jobs'],
}

export function hasPermission(role: Role | undefined, action: string): boolean {
  if (!role) return false
  return PERMISSIONS[role]?.includes(action) ?? false
}