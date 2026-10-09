// Client-side image preparation: decode, downscale, re-encode.
//
// A phone photo is 4–8 MB; sending it raw would blow up the request body and the
// model's context for no gain. Everything is scaled to a longest side of 1568 px
// (what the vision models are trained around) and re-encoded to WebP, with JPEG as
// a fallback. No image library is pulled in — createImageBitmap + canvas are enough.

export const MAX_IMAGE_DIM = 1568;
/** Mirrors settings.image_max_count on the server. */
export const MAX_ATTACHMENTS = 6;
const QUALITY = 0.85;

export interface ProcessedImage {
  /** ready to display as a preview */
  dataUrl: string;
  /** raw base64, exactly what goes on the wire */
  base64: string;
  name: string;
  width: number;
  height: number;
  bytes: number;
}

/** What `send()` needs from an attachment — a freshly processed one or a TurnImage. */
export type AttachableImage = Pick<
  ProcessedImage,
  "dataUrl" | "base64" | "name" | "width" | "height"
>;

let webpSupport: boolean | null = null;

function supportsWebp(): boolean {
  if (webpSupport === null) {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    webpSupport = canvas.toDataURL("image/webp").startsWith("data:image/webp");
  }
  return webpSupport;
}

function toBlob(canvas: HTMLCanvasElement, type: string): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("the image could not be encoded"))),
      type,
      QUALITY
    );
  });
}

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("the image could not be read"));
    reader.readAsDataURL(blob);
  });
}

/** Downscale and re-encode one picked/pasted/dropped file. Throws a readable message. */
export async function processImageFile(file: File): Promise<ProcessedImage> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    // HEIC and friends land here: the browser cannot decode them at all
    throw new Error(`${file.name || "that file"} is not an image this browser can read`);
  }
  try {
    const scale = Math.min(1, MAX_IMAGE_DIM / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("this browser cannot resize images");
    ctx.drawImage(bitmap, 0, 0, width, height);

    const blob = await toBlob(canvas, supportsWebp() ? "image/webp" : "image/jpeg");
    const dataUrl = await toDataUrl(blob);
    return {
      dataUrl,
      base64: dataUrl.slice(dataUrl.indexOf(",") + 1),
      name: file.name || "image",
      width,
      height,
      bytes: blob.size,
    };
  } finally {
    bitmap.close();
  }
}

/** Process a batch, keeping the first `limit` images and reporting what was dropped. */
export async function processImageFiles(
  files: File[],
  limit: number
): Promise<{ images: ProcessedImage[]; errors: string[] }> {
  const picked = files.filter((f) => f.type.startsWith("image/")).slice(0, Math.max(0, limit));
  const errors: string[] = [];
  if (picked.length < files.length) {
    const skipped = files.length - picked.length;
    errors.push(skipped === 1 ? "one file was skipped" : `${skipped} files were skipped`);
  }
  const images = await Promise.all(
    picked.map((file) =>
      processImageFile(file).catch((err: unknown) => {
        errors.push(err instanceof Error ? err.message : "that image could not be attached");
        return null;
      })
    )
  );
  return { images: images.filter((i): i is ProcessedImage => i !== null), errors };
}

/** Human-readable size for the attachment chip. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
