export const MAX_AUDIO_BYTES = 3 * 1024 * 1024;
export const AUDIO_BODY_LIMIT = 4 * Math.ceil(MAX_AUDIO_BYTES / 3) + 1024;

export function checkVoiceFile(file: File) {
  if (!file.name.toLowerCase().endsWith('.wav') || file.size < 44 || file.size > MAX_AUDIO_BYTES) {
    throw new Error('Choose a WAV clip up to 3 MiB. Use 16-bit PCM, 0.5–30 seconds, mono/stereo at 8–48 kHz.');
  }
}

export async function encodeVoice(file: File) {
  checkVoiceFile(file);
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length < 44 || bytes.length > MAX_AUDIO_BYTES ||
      String.fromCharCode(...bytes.slice(0,4)) !== 'RIFF' || String.fromCharCode(...bytes.slice(8,12)) !== 'WAVE') {
    throw new Error('Choose a valid PCM WAV clip, or type your question instead.');
  }
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset,offset+8192));
  return {media_type:'audio/wav',data_base64:btoa(binary),share_with_ai:true};
}

export function parseTranscript(value: unknown): string {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('The transcript could not be confirmed. Type your question instead.');
  const v = value as Record<string,unknown>;
  if (Object.keys(v).length !== 5 || v.source !== 'audio_transcription' || v.needs_review !== true ||
      typeof v.request_id !== 'string' || !/^[0-9a-f-]{36}$/.test(v.request_id) ||
      typeof v.duration_ms !== 'number' || !Number.isInteger(v.duration_ms) || v.duration_ms < 500 || v.duration_ms > 30000 ||
      typeof v.text !== 'string' || !v.text.trim() || v.text.length > 2000 || new TextEncoder().encode(v.text).length > 8192) {
    throw new Error('The transcript could not be confirmed. Type your question instead.');
  }
  return v.text.trim();
}
