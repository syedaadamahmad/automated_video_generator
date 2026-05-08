// // src/app/api/proxy/[...path]/route.ts
// // Catch-all proxy: /api/proxy/anything → http://localhost:8100/anything
// // Injects X-User-Id and X-User-Role headers from the NextAuth session.

// import { getServerSession } from 'next-auth'
// import { authOptions } from '@/lib/auth-options'
// import { NextRequest, NextResponse } from 'next/server'

// const VEO_API = process.env.VEO_API_URL ?? 'http://localhost:8100'

// // Next.js 15+: params is a Promise — must be awaited.
// type RouteContext = { params: Promise<{ path: string[] }> }

// async function handler(request: NextRequest, context: RouteContext) {
//   const session = await getServerSession(authOptions)

//   const { path } = await context.params
//   const targetPath = '/' + (path ?? []).join('/')
//   const targetUrl  = new URL(targetPath, VEO_API)

//   // Forward query params
//   request.nextUrl.searchParams.forEach((v, k) => targetUrl.searchParams.set(k, v))

//   // Build forwarded headers — strip Next.js internals
//   const headers = new Headers()
//   request.headers.forEach((v, k) => {
//     if (!['host', 'connection', 'transfer-encoding'].includes(k)) {
//       headers.set(k, v)
//     }
//   })

//   // session.user.email and .role typed via src/types/next-auth.d.ts
//   headers.set('X-User-Id',   session?.user?.email ?? 'anonymous')
//   headers.set('X-User-Role', session?.user?.role  ?? 'viewer')

//   const method = request.method.toUpperCase()
//   let body: BodyInit | null = null
//   if (!['GET', 'HEAD'].includes(method)) {
//     body = await request.blob()
//   }

//   try {
//     const upstream = await fetch(targetUrl.toString(), {
//       method,
//       headers,
//       body,
//       redirect: 'manual',
//     })

//     const resHeaders = new Headers()
//     upstream.headers.forEach((v, k) => {
//       if (!['transfer-encoding', 'connection', 'keep-alive'].includes(k)) {
//         resHeaders.set(k, v)
//       }
//     })

//     return new NextResponse(upstream.body, {
//       status:  upstream.status,
//       headers: resHeaders,
//     })
//   } catch (err) {
//     console.error('[PROXY] upstream error:', err)
//     return NextResponse.json(
//       { error: 'Cannot reach veo_main.py — start it with: python veo_main.py' },
//       { status: 502 },
//     )
//   }
// }

// export const GET     = handler
// export const POST    = handler
// export const PUT     = handler
// export const PATCH   = handler
// export const DELETE  = handler
// export const HEAD    = handler
// export const OPTIONS = handler


























// src/app/api/proxy/[...path]/route.ts
// Catch-all proxy: /api/proxy/anything → http://localhost:8100/anything
// Injects X-User-Id and X-User-Role headers from the NextAuth session.

import { getServerSession } from 'next-auth'
import { authOptions } from '@/lib/auth-options'
import { NextRequest, NextResponse } from 'next/server'

const VEO_API = process.env.VEO_API_URL ?? 'http://localhost:8100'

// Next.js 15+: params is a Promise — must be awaited.
type RouteContext = { params: Promise<{ path: string[] }> }

async function handler(request: NextRequest, context: RouteContext) {
  const session = await getServerSession(authOptions)

  const { path } = await context.params
  const targetPath = '/' + (path ?? []).join('/')
  const targetUrl  = new URL(targetPath, VEO_API)

  // Forward query params
  request.nextUrl.searchParams.forEach((v, k) => targetUrl.searchParams.set(k, v))

  // Build forwarded headers — strip Next.js internals
  const headers = new Headers()
  request.headers.forEach((v, k) => {
    if (!['host', 'connection', 'transfer-encoding'].includes(k)) {
      headers.set(k, v)
    }
  })

  // session.user.email and .role typed via src/types/next-auth.d.ts
  headers.set('X-User-Id',   session?.user?.email ?? 'anonymous')
  headers.set('X-User-Role', session?.user?.role  ?? 'viewer')

  // Internal secret — proves this request came from the Next.js proxy,
  // not from a client hitting the FastAPI directly.
  // Must match INTERNAL_SECRET in veo.env.
  const internalSecret = process.env.INTERNAL_SECRET ?? ''
  if (internalSecret) {
    headers.set('X-Internal-Secret', internalSecret)
  }

  const method = request.method.toUpperCase()
  let body: BodyInit | null = null
  if (!['GET', 'HEAD'].includes(method)) {
    body = await request.blob()
  }

  try {
    const upstream = await fetch(targetUrl.toString(), {
      method,
      headers,
      body,
      redirect: 'manual',
    })

    const resHeaders = new Headers()
    upstream.headers.forEach((v, k) => {
      if (!['transfer-encoding', 'connection', 'keep-alive'].includes(k)) {
        resHeaders.set(k, v)
      }
    })

    return new NextResponse(upstream.body, {
      status:  upstream.status,
      headers: resHeaders,
    })
  } catch (err) {
    console.error('[PROXY] upstream error:', err)
    return NextResponse.json(
      { error: 'Cannot reach veo_main.py — start it with: python veo_main.py' },
      { status: 502 },
    )
  }
}

export const GET     = handler
export const POST    = handler
export const PUT     = handler
export const PATCH   = handler
export const DELETE  = handler
export const HEAD    = handler
export const OPTIONS = handler