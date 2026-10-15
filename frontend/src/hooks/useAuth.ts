import { useState, useCallback } from 'react'
import { login as apiLogin } from '../api/client'

const TOKEN_KEY = 'aura_token'

interface DecodedUser {
  sub: string
  email?: string
  exp: number
}

/** Minimal base64url JWT payload decoder (no crypto verification) */
function decodeJwt(token: string): DecodedUser | null {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    // Pad base64url to standard base64
    const padded = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(
      payload.length + ((4 - (payload.length % 4)) % 4),
      '=',
    )
    const decoded = JSON.parse(atob(padded))
    return decoded as DecodedUser
  } catch {
    return null
  }
}

function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

function isTokenValid(token: string | null): boolean {
  if (!token) return false
  const decoded = decodeJwt(token)
  if (!decoded) return false
  // Check expiry (exp is seconds since epoch)
  return decoded.exp * 1000 > Date.now()
}

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => {
    const stored = getStoredToken()
    return isTokenValid(stored) ? stored : null
  })

  const isAuthenticated = token !== null && isTokenValid(token)
  const user = token ? decodeJwt(token) : null

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const response = await apiLogin(email, password)
    const { access_token } = response
    localStorage.setItem(TOKEN_KEY, access_token)
    setToken(access_token)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])

  return { isAuthenticated, user, login, logout, token }
}
