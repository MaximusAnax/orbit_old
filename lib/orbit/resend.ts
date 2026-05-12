export interface ResendEmailInput {
  apiKey: string;
  from: string;
  to: string;
  subject: string;
  html: string;
  text: string;
  idempotencyKey?: string;
}

export interface ResendEmailResult {
  id: string;
}

export async function sendResendEmail(input: ResendEmailInput, fetchImpl = fetch): Promise<ResendEmailResult> {
  const response = await fetchImpl("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${input.apiKey}`,
      "Content-Type": "application/json",
      ...(input.idempotencyKey ? { "Idempotency-Key": input.idempotencyKey } : {}),
    },
    body: JSON.stringify({
      from: input.from,
      to: [input.to],
      subject: input.subject,
      html: input.html,
      text: input.text,
    }),
  });

  const payload = await response.json().catch(async () => ({ message: await response.text() }));

  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "message" in payload
        ? String(payload.message)
        : `Resend request failed with status ${response.status}.`;
    throw new Error(message);
  }

  if (!payload || typeof payload !== "object" || !("id" in payload)) {
    throw new Error("Resend response did not include a message id.");
  }

  return { id: String(payload.id) };
}
