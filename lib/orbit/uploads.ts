export const AUDIO_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024;
export const IMAGE_UPLOAD_LIMIT_BYTES = 8 * 1024 * 1024;

export function validateUploadedFile(file: File, options: { allowedTypes: string[]; maxBytes: number }) {
  if (!options.allowedTypes.includes(file.type)) {
    throw new Error("Unsupported file type.");
  }

  if (file.size > options.maxBytes) {
    throw new Error("File is too large.");
  }
}

export function fallbackTranscript(file: File) {
  return `Audio note uploaded from ${file.name}. Add an OpenAI API key to transcribe this capture automatically.`;
}

export function fallbackCardText(file: File) {
  return `Business card image uploaded from ${file.name}. Add an OpenAI API key to extract the card text automatically.`;
}
