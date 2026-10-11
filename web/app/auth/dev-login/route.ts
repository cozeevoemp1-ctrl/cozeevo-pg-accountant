import { NextResponse, type NextRequest } from "next/server";
import { createHmac } from "node:crypto";

// DEV-ONLY demo login for running the real PWA against the local sandbox API
// (tests/sandbox/sandbox_server.py, fake data). Signs a LOCAL HS256 token that the API
// accepts via SUPABASE_JWT_SECRET, and stores it as the @supabase/ssr session cookie —
// middleware, api.ts and pages only read that cookie (getSession), so nothing else changes.
//
// 404 unless ALL of: `next dev`, DEV_DEMO_LOGIN=1, DEV_DEMO_JWT_SECRET set.
// Those are server-only vars, never set in production (see web/.env.local.example).
// Usage: http://localhost:3000/auth/dev-login  (?role=staff for the staff view)

const b64url = (s: string | Buffer) => Buffer.from(s).toString("base64url");

export async function GET(req: NextRequest) {
  const secret = process.env.DEV_DEMO_JWT_SECRET;
  if (process.env.NODE_ENV === "production" || process.env.DEV_DEMO_LOGIN !== "1" || !secret) {
    return new NextResponse("Not found", { status: 404 });
  }

  const role = req.nextUrl.searchParams.get("role") === "staff" ? "staff" : "admin";
  const now = Math.floor(Date.now() / 1000);
  const exp = now + 7 * 24 * 3600; // far enough ahead that supabase-js never tries a refresh
  const user = {
    id: "00000000-0000-4000-8000-000000000d30",
    aud: "authenticated",
    role: "authenticated",
    email: "demo@sandbox.local",
    app_metadata: { role, org_id: 1 },
    user_metadata: { name: role === "admin" ? "Demo Manager" : "Demo Staff" },
    created_at: new Date(0).toISOString(),
  };
  const claims = { ...user, sub: user.id, iat: now, exp };
  delete (claims as Partial<typeof user>).id;

  const unsigned = `${b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }))}.${b64url(JSON.stringify(claims))}`;
  const access_token = `${unsigned}.${createHmac("sha256", secret).update(unsigned).digest("base64url")}`;

  const session = {
    access_token,
    token_type: "bearer",
    expires_in: exp - now,
    expires_at: exp,
    refresh_token: "dev-demo-no-refresh",
    user,
  };

  // @supabase/ssr cookie: sb-<project-ref>-auth-token = "base64-" + base64url(session JSON)
  const ref = new URL(process.env.NEXT_PUBLIC_SUPABASE_URL ?? "http://local").hostname.split(".")[0];
  const res = NextResponse.redirect(new URL("/", req.url));
  res.cookies.set(`sb-${ref}-auth-token`, `base64-${b64url(JSON.stringify(session))}`, {
    path: "/",
    sameSite: "lax",
    maxAge: exp - now,
  });
  return res;
}
