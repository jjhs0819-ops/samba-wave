import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Authentication Middleware
 *
 * JWT 토큰 검증으로 보호된 경로 접근 제어
 */

// Samba 경로 인증 필수 (로그인 없이 접근 차단)
const PROTECTED_PATHS: string[] = ["/samba"];

// Routes that should redirect to home if already authenticated
const AUTH_PATHS = ["/login", "/signup"];

// Public paths that don't require any checks
const PUBLIC_PATHS = [
  "/",
  "/api",
  "/_next",
  "/favicon.ico",
  "/images",
  "/fonts",
];

const ACCESS_TOKEN_COOKIE = "app_access_token";

/** JWT 토큰 payload를 디코딩하여 만료 여부 확인 */
function isTokenValid(token: string): boolean {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return false
    const payload = JSON.parse(atob(parts[1]))
    if (!payload.exp || !payload.sub) return false
    // 만료 시간 체크 (30초 여유)
    return payload.exp * 1000 > Date.now() - 30_000
  } catch {
    return false
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip middleware for public assets and API routes
  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  // JWT 토큰 유효성 검증 (존재 여부가 아닌 실제 값 확인)
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  const sambaToken = request.cookies.get("samba_user")?.value;
  const isAuthenticated =
    (!!accessToken && isTokenValid(accessToken)) ||
    (!!sambaToken && isTokenValid(sambaToken));

  // Check if current path is protected (로그인/회원가입 페이지는 제외)
  const isProtectedPath =
    PROTECTED_PATHS.some((path) => pathname.startsWith(path)) &&
    !pathname.startsWith("/samba/login") &&
    !pathname.startsWith("/samba/sign-up");

  // Redirect unauthenticated users from protected routes to login
  if (isProtectedPath && !isAuthenticated) {
    // 만료된 쿠키 삭제
    const loginPath = pathname.startsWith("/samba") ? "/samba/login" : "/login";
    const loginUrl = new URL(loginPath, request.url);
    loginUrl.searchParams.set("redirect", pathname);
    const response = NextResponse.redirect(loginUrl);
    // 유효하지 않은 쿠키 제거
    if (sambaToken && !isTokenValid(sambaToken)) {
      response.cookies.delete("samba_user");
    }
    return response;
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
