import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

const ALLOWED_FILES = new Set([
  "visual_state.json",
  "evolution_validation.json",
  "training_roadmap.json",
  "training_runtime.json"
]);

function noStoreHeaders(sourceKey: string): HeadersInit {
  return {
    "Cache-Control": "no-store, max-age=0, must-revalidate",
    "x-state-source": sourceKey
  };
}

function normalizePathToken(raw: string): string {
  return raw.replace(/^\/+/, "").replace(/\.\.+/g, "").trim();
}

async function readFromSupabaseStorage(name: string): Promise<{ payload: unknown; sourceKey: string } | null> {
  const supabaseUrl = String(process.env.SUPABASE_URL || "").trim().replace(/\/+$/, "");
  const serviceRoleKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();
  const bucket = (String(process.env.SUPABASE_STATE_BUCKET || "monitor-state").trim() || "monitor-state").replace(/^\/+|\/+$/g, "");
  const prefix = String(process.env.SUPABASE_STATE_PREFIX || "state").trim().replace(/^\/+|\/+$/g, "");

  if (!supabaseUrl || !serviceRoleKey || !bucket) {
    return null;
  }

  const objectPath = prefix ? `${prefix}/${name}` : name;
  const encodedBucket = encodeURIComponent(bucket);
  const encodedPath = objectPath
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
  const endpoint = `${supabaseUrl}/storage/v1/object/${encodedBucket}/${encodedPath}`;

  const resp = await fetch(endpoint, {
    method: "GET",
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`
    },
    cache: "no-store"
  });
  if (!resp.ok) {
    return null;
  }

  const text = await resp.text();
  if (!text) {
    return null;
  }
  try {
    const payload = JSON.parse(text);
    return { payload, sourceKey: "SOURCE_SUPABASE" };
  } catch {
    return null;
  }
}

async function readFromStaticState(name: string): Promise<{ payload: unknown; sourceKey: string } | null> {
  const filePath = path.join(process.cwd(), "public", "state", name);
  try {
    const raw = await readFile(filePath, "utf-8");
    const payload = JSON.parse(raw);
    return { payload, sourceKey: "SOURCE_STATIC" };
  } catch {
    return null;
  }
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ name: string }> }
): Promise<NextResponse> {
  const params = await context.params;
  const name = normalizePathToken(String(params.name || ""));
  if (!ALLOWED_FILES.has(name)) {
    return NextResponse.json(
      {
        error: "STATE_NOT_FOUND",
        file: name
      },
      {
        status: 404,
        headers: noStoreHeaders("SOURCE_UNKNOWN")
      }
    );
  }

  const fromSupabase = await readFromSupabaseStorage(name);
  if (fromSupabase) {
    return NextResponse.json(fromSupabase.payload, {
      status: 200,
      headers: noStoreHeaders(fromSupabase.sourceKey)
    });
  }

  const fromStatic = await readFromStaticState(name);
  if (fromStatic) {
    return NextResponse.json(fromStatic.payload, {
      status: 200,
      headers: noStoreHeaders(fromStatic.sourceKey)
    });
  }

  return NextResponse.json(
    {
      error: "STATE_UNAVAILABLE",
      file: name
    },
    {
      status: 503,
      headers: noStoreHeaders("SOURCE_UNKNOWN")
    }
  );
}
