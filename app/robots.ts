import type { MetadataRoute } from "next";

import { getBaseUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  const base = getBaseUrl().toString().replace(/\/$/, "");
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/"]
      }
    ],
    sitemap: `${base}/sitemap.xml`
  };
}
