/**
 * API Client with Authentication
 *
 * Handles all API requests with automatic token management.
 */

// Environment-based API URL selection
const isDev = process.env.NEXT_PUBLIC_ENV === "development";
const API_BASE_URL = isDev
  ? (process.env.NEXT_PUBLIC_API_URL_DEV || "http://localhost:28080")
  : (process.env.NEXT_PUBLIC_API_URL_PROD || "http://localhost:28080");

export interface LoginResponse {
  user_id: string;
  app_auth_token: string;
  refresh_token: string;
  nickname: string | null;
}

export interface UserInfo {
  id: string;
  nickname: string;
  email: string | null;
  auth_type: string;
  is_admin: boolean;
  is_premium: boolean;
}

export interface RefreshTokenResponse {
  app_auth_token: string;
  refresh_token: string;
}

// Token storage keys
const ACCESS_TOKEN_KEY = "app_access_token";
const REFRESH_TOKEN_KEY = "app_refresh_token";

/**
 * Get stored access token
 */
export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

/**
 * Get stored refresh token
 */
export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

/**
 * Store tokens in localStorage and sync with HTTP-only cookies
 */
export function setTokens(accessToken: string, refreshToken: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);

  // Sync with HTTP-only cookies for SSR and middleware
  syncTokensToCookies(accessToken, refreshToken);
}

/**
 * Sync tokens to HTTP-only cookies via session API
 */
async function syncTokensToCookies(
  accessToken: string,
  refreshToken: string
): Promise<void> {
  try {
    await fetch("/api/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accessToken, refreshToken }),
    });
  } catch (error) {
    console.error("Failed to sync tokens to cookies:", error);
  }
}

/**
 * Clear stored tokens
 */
export function clearTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);

  // Clear HTTP-only cookies
  clearTokenCookies();
}

/**
 * Clear HTTP-only token cookies via session API
 */
async function clearTokenCookies(): Promise<void> {
  try {
    await fetch("/api/auth/session", {
      method: "DELETE",
    });
  } catch (error) {
    console.error("Failed to clear token cookies:", error);
  }
}

/**
 * Check if user has valid tokens
 */
export function hasTokens(): boolean {
  return getAccessToken() !== null;
}

/**
 * API Error class for typed error handling
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown
  ) {
    super(`API Error: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/**
 * Refresh the access token using refresh token
 */
async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      clearTokens();
      return false;
    }

    const data: RefreshTokenResponse = await response.json();
    setTokens(data.app_auth_token, data.refresh_token);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}

/**
 * Make an authenticated API request
 */
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  retry = true
): Promise<T> {
  const accessToken = getAccessToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  if (accessToken) {
    (headers as Record<string, string>)["Authorization"] =
      `Bearer ${accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  // Handle 401 - try refresh token
  if (response.status === 401 && retry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiRequest<T>(endpoint, options, false);
    }
    throw new ApiError(401, "Unauthorized", { needsLogin: true });
  }

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, response.statusText, data);
  }

  // Handle empty response
  const text = await response.text();
  if (!text) return {} as T;

  return JSON.parse(text) as T;
}

// ============================================
// Auth API Methods
// ============================================

/**
 * Login with email and password
 */
export async function emailLogin(
  email: string,
  password: string
): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/api/v1/auth/email/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/**
 * Sign up with email and password
 */
export async function emailSignUp(
  email: string,
  password: string,
  username: string
): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/api/v1/auth/email/sign-up", {
    method: "POST",
    body: JSON.stringify({ email, password, username }),
  });
}

/**
 * Get current user info
 */
export async function getCurrentUser(): Promise<UserInfo> {
  return apiRequest<UserInfo>("/api/v1/auth/me");
}

/**
 * Refresh tokens
 */
export async function refreshTokens(): Promise<RefreshTokenResponse> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new ApiError(401, "No refresh token");
  }

  return apiRequest<RefreshTokenResponse>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

// ============================================
// Generic API Methods
// ============================================

export const api = {
  get: <T>(endpoint: string) => apiRequest<T>(endpoint),
  post: <T>(endpoint: string, body: unknown) =>
    apiRequest<T>(endpoint, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(endpoint: string, body: unknown) =>
    apiRequest<T>(endpoint, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(endpoint: string, body: unknown) =>
    apiRequest<T>(endpoint, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(endpoint: string) =>
    apiRequest<T>(endpoint, { method: "DELETE" }),
};
