import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { coerceLocale, resolveBestLocale, withLocale } from "@/lib/i18n";

const STATIC_FILE_PATTERN = /\.[a-zA-Z0-9]+$/;

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/sitemap") ||
    pathname.startsWith("/robots") ||
    STATIC_FILE_PATTERN.test(pathname)
  ) {
    return NextResponse.next();
  }

  const pathSegments = pathname.split("/").filter(Boolean);
  const pathLocale = coerceLocale(pathSegments[0]);
  if (pathLocale) {
    return NextResponse.next();
  }

  const locale = resolveBestLocale({
    cookieLocale: request.cookies.get("preferred_locale")?.value,
    acceptLanguage: request.headers.get("accept-language"),
    countryCode: request.headers.get("x-vercel-ip-country") ?? request.headers.get("cf-ipcountry")
  });

  const redirectUrl = request.nextUrl.clone();
  redirectUrl.pathname = withLocale(pathname, locale);
  redirectUrl.search = search;

  const response = NextResponse.redirect(redirectUrl);
  response.cookies.set("preferred_locale", locale, {
    path: "/",
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 365
  });
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]
};
