/**
 * Internal deep links are a closed set of app routes.
 *
 * Anything outside that set — external URLs, unknown schemes, or free-form
 * paths — is refused. Callers must never fall through to
 * `window.location.assign`.
 */

const ALLOWED_PREFIXES = [
  '/todos',
  '/notifications',
  '/opportunities',
  '/lifecycle-board',
  '/products',
  '/product-change-sets/',
  '/projects/',
  '/operations',
  '/retirement-plans/',
  '/stage-gates/',
  '/admin/',
] as const

export type DeepLinkDecision =
  | { ok: true; path: string }
  | { ok: false; reason: 'EMPTY' | 'EXTERNAL' | 'UNKNOWN_SCHEME' | 'NOT_ALLOWLISTED' }

export function resolveInternalDeepLink(raw: string): DeepLinkDecision {
  const link = raw.trim()
  if (!link) return { ok: false, reason: 'EMPTY' }

  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(link)) {
    return { ok: false, reason: 'UNKNOWN_SCHEME' }
  }
  if (link.startsWith('//')) {
    return { ok: false, reason: 'EXTERNAL' }
  }
  if (!link.startsWith('/')) {
    return { ok: false, reason: 'NOT_ALLOWLISTED' }
  }

  const path = link.split(/[?#]/, 1)[0] ?? link
  if (ALLOWED_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix))) {
    return { ok: true, path: link }
  }
  return { ok: false, reason: 'NOT_ALLOWLISTED' }
}
