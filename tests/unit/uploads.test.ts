import { describe, expect, it } from "vitest";
import {
  AUDIO_UPLOAD_LIMIT_BYTES,
  fallbackCardText,
  fallbackTranscript,
  validateUploadedFile,
} from "@/lib/orbit/uploads";

describe("upload validation", () => {
  it("accepts allowed files under the size limit", () => {
    const file = new File(["hello"], "note.webm", { type: "audio/webm" });

    expect(() =>
      validateUploadedFile(file, {
        allowedTypes: ["audio/webm"],
        maxBytes: AUDIO_UPLOAD_LIMIT_BYTES,
      }),
    ).not.toThrow();
  });

  it("rejects unsupported file types", () => {
    const file = new File(["hello"], "note.txt", { type: "text/plain" });

    expect(() =>
      validateUploadedFile(file, {
        allowedTypes: ["audio/webm"],
        maxBytes: AUDIO_UPLOAD_LIMIT_BYTES,
      }),
    ).toThrow("Unsupported file type.");
  });

  it("returns development fallbacks that preserve file context", () => {
    const audio = new File(["hello"], "drive-note.webm", { type: "audio/webm" });
    const card = new File(["hello"], "business-card.png", { type: "image/png" });

    expect(fallbackTranscript(audio)).toContain("drive-note.webm");
    expect(fallbackCardText(card)).toContain("business-card.png");
  });
});
