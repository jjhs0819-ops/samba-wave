import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Authentication Middleware
 *
 * Protects routes that require authentication.
 */

// Routes that require authentication (none for now since we removed admin/form/match)
const PROTECTED_PATHS: string[] = [];

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

  // Get the access token from cookies
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  const isAuthenticated = !!accessToken;

  // Check if current path is protected
  const isProtectedPath = PROTECTED_PATHS.some((path) =>
    pathname.startsWith(path)
  );

  // Check if current path is an auth path (login/signup)
  const isAuthPath = AUTH_PATHS.some((path) => pathname.startsWith(path));

  // Redirect unauthenticated users from protected routes to login
  if (isProtectedPath && !isAuthenticated) {
    const loginUrl = new URL("/login", request.url);
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
