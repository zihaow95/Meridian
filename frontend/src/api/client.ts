export type ApiErrorShape = {
  code: string
  message: string
  details: Record<string, unknown>
  trace_id: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>
  readonly traceId: string

  constructor(status: number, body: ApiErrorShape) {
    super(body.message)
    this.status = status
    this.code = body.code
    this.details = body.details
    this.traceId = body.trace_id
  }
}

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

export async function apiFetch<T>(
  input: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  const method = (init.method ?? 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
    const csrf = getCookie('csrftoken')
    if (csrf) headers.set('X-CSRFToken', csrf)
  }

  const response = await fetch(input, {
    ...init,
    headers,
    credentials: 'include',
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  })

  if (response.status === 204) {
    return undefined as unknown as T
  }

  const contentType = response.headers.get('content-type') ?? ''
  const isJson = contentType.includes('application/json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    if (data && typeof data === 'object' && 'code' in data && 'trace_id' in data) {
      throw new ApiError(response.status, data as ApiErrorShape)
    }
    throw new Error(`Request failed: ${response.status}`)
  }

  return data as T
}
