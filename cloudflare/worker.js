const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "content-type,authorization,x-requested-with",
  "access-control-max-age": "86400",
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (new URL(request.url).pathname === "/__gateway/health") {
      const origin = await env.FLOWER_DEMO_CONFIG.get("origin");
      return json({
        status: "ok",
        originConfigured: Boolean(origin),
      });
    }

    const origin = await env.FLOWER_DEMO_CONFIG.get("origin");
    if (!origin) {
      return json(
        {
          error: "origin_not_configured",
          message: "FLOWER_DEMO_CONFIG KV key `origin` is missing.",
        },
        503,
      );
    }

    return proxyToOrigin(request, origin);
  },
};

async function proxyToOrigin(request, origin) {
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(incomingUrl.pathname + incomingUrl.search, origin);
  const headers = new Headers(request.headers);

  headers.delete("host");
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }

  const proxiedRequest = new Request(targetUrl.toString(), {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual",
  });

  const response = await fetch(proxiedRequest);
  const responseHeaders = new Headers(response.headers);

  for (const header of HOP_BY_HOP_HEADERS) {
    responseHeaders.delete(header);
  }

  for (const [key, value] of Object.entries(CORS_HEADERS)) {
    responseHeaders.set(key, value);
  }
  responseHeaders.set("x-flower-gateway", "cloudflare-worker");

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...CORS_HEADERS,
      "x-flower-gateway": "cloudflare-worker",
    },
  });
}
