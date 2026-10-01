export class BodyTooLarge extends Error {}

/** @param {Request} request @param {number} limit */
export async function readLimitedBody(request, limit) {
  const declared = request.headers.get('content-length');
  if (declared && Number(declared) > limit) throw new BodyTooLarge('Request body exceeds limit');
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new BodyTooLarge('Request body exceeds limit'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return body.buffer;
}

/** @param {Request} request @param {number} limit */
export async function readLimitedJson(request, limit) {
  return JSON.parse(new TextDecoder().decode(await readLimitedBody(request, limit)));
}
