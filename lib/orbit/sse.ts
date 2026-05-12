export interface ServerSentEvent<T = unknown> {
  event: string;
  data: T;
}

export function serializeSseEvent(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function parseSseBuffer(buffer: string) {
  const segments = buffer.split("\n\n");
  const remainder = segments.pop() ?? "";
  const events = segments
    .map(parseSseEvent)
    .filter((event): event is ServerSentEvent => Boolean(event));

  return {
    events,
    remainder,
  };
}

function parseSseEvent(segment: string) {
  const trimmed = segment.trim();
  if (!trimmed) return null;

  const lines = trimmed.split("\n");
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  return {
    event,
    data: JSON.parse(dataLines.join("\n")),
  };
}
