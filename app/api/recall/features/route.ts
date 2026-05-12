import { NextResponse } from "next/server";
import { advancedRecallFlags } from "@/lib/orbit/action-layer";

export async function GET() {
  return NextResponse.json({
    features: advancedRecallFlags(),
  });
}
