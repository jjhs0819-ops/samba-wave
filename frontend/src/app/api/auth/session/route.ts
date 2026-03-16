import { cookies } from "next/headers";
import { NextResponse } from "next/server";

/**
 * Session API Route
 *
 * Manages HTTP-only authentication cookies for secure token storage.
 */

const ACCESS_TOKEN_COOKIE = "app_access_token";
const REFRESH_TOKEN_COOKIE = "app_refresh_token";

// Cookie options
const cookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

/**
 * POST /api/auth/session
 * Set authentication tokens as HTTP-only cookies
 */
export async function POST(request: Request) {
  try {
    const { accessToken, refreshToken } = await request.json();

    if (!accessToken) {
      return NextResponse.json(
        { error: "Access token is required" },
        { status: 400 }
      );
    }

    const cookieStore = await cookies();

    // Set access token (12 hours expiry)
    cookieStore.set(ACCESS_TOKEN_COOKIE, accessToken, {
      ...cookieOptions,
      maxAge: 12 * 60 * 60, // 12 hours
    });

    // Set refresh token if provided (30 days expiry)
    if (refreshToken) {
      cookieStore.set(REFRESH_TOKEN_COOKIE, refreshToken, {
        ...cookieOptions,
        maxAge: 30 * 24 * 60 * 60, // 30 days
      });
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Session POST error:", error);
    return NextResponse.json(
      { error: "Failed to set session" },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/auth/session
 * Clear authentication cookies (logout)
 */
export async function DELETE() {
  try {
    const cookieStore = await cookies();

    cookieStore.delete(ACCESS_TOKEN_COOKIE);
    cookieStore.delete(REFRESH_TOKEN_COOKIE);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Session DELETE error:", error);
    return NextResponse.json(
      { error: "Failed to clear session" },
      { status: 500 }
    );
  }
}

/**
 * GET /api/auth/session
 * Check if session exists
 */
export async function GET() {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE);

    return NextResponse.json({
      authenticated: !!accessToken?.value,
    });
  } catch (error) {
    console.error("Session GET error:", error);
    return NextResponse.json({ authenticated: false });
  }
}
