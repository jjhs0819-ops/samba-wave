import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Authentication Middleware
 *
 * Protects routes that require authentication.
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

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip middleware for public assets and API routes
  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  // Get the access token from cookies (Samba 유저는 samba_user 쿠키 사용)
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  const sambaUser = request.cookies.get("samba_user")?.value;
  const isAuthenticated = !!accessToken || !!sambaUser;

  // Check if current path is protected (로그인 페이지는 제외)
  const isProtectedPath =
    PROTECTED_PATHS.some((path) => pathname.startsWith(path)) &&
    !pathname.startsWith("/samba/login");

  // Check if current path is an auth path (login/signup)
  const isAuthPath = AUTH_PATHS.some((path) => pathname.startsWith(path));

  // Redirect unauthenticated users from protected routes to login
  if (isProtectedPath && !isAuthenticated) {
    // Samba 경로는 Samba 전용 로그인으로 리다이렉트
    const loginPath = pathname.startsWith("/samba") ? "/samba/login" : "/login";
    const loginUrl = new URL(loginPath, request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Optionally redirect authenticated users from auth pages to home
  // (commented out to allow viewing login page when logged in)
  // if (isAuthPath && isAuthenticated) {
  //   return NextResponse.redirect(new URL("/", request.url));
  // }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
