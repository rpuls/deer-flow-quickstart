import { NextResponse } from "next/server";

// Liveness probe for the frontend container. It deliberately does not touch the
// Gateway: a platform health check that fails while the Gateway restarts would
// take the web service down with it. Gateway health has its own probe at
// /health/ready.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "deer-flow-frontend" });
}
