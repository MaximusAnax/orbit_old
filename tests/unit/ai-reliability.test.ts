import { describe, expect, it } from "vitest";
import { runReliableAiCall } from "@/lib/orbit/ai";

describe("AI reliability helpers", () => {
  it("retries transient provider failures", async () => {
    let attempts = 0;

    const result = await runReliableAiCall(
      async () => {
        attempts += 1;
        if (attempts === 1) {
          throw new Error("provider unavailable");
        }
        return "ok";
      },
      { operationName: "test operation", retries: 1, timeoutMs: 100 },
    );

    expect(result).toBe("ok");
    expect(attempts).toBe(2);
  });

  it("returns a visible timeout error", async () => {
    await expect(
      runReliableAiCall(() => new Promise(() => undefined), {
        operationName: "slow operation",
        retries: 0,
        timeoutMs: 5,
      }),
    ).rejects.toThrow("slow operation timed out after 5ms");
  });
});
