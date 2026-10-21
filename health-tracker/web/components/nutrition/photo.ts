// A meal photo ready to send: at most 1568 px on the long edge (what the model sees anyway) as a JPEG at quality 0.8,
// about 200-400 kB. Drawing it on a canvas applies the camera's rotation and leaves every bit of metadata behind, so a
// location never leaves the phone (the server strips it again, tools/nutrition/photos.py).

const LONG_EDGE = 1568;
const QUALITY = 0.8;

export async function preparePhoto(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, LONG_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("photo"))), "image/jpeg", QUALITY),
  );
}

/** The photo's own time (HH:MM, from the file's last-modified time, which a phone camera sets when it takes it). */
export function photoTime(file: File): string | null {
  if (!file.lastModified) return null;
  const d = new Date(file.lastModified);
  if (Date.now() - d.getTime() > 12 * 3600 * 1000) return null; // an old photo from the library: the clock is a better guess
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** BarcodeDetector where the browser has it (Chrome on Android, not Safari): the EAN on a photo of a package. */
export async function readBarcode(file: Blob): Promise<string | null> {
  const Detector = (
    globalThis as { BarcodeDetector?: new (o: { formats: string[] }) => { detect: (b: ImageBitmap) => Promise<{ rawValue: string }[]> } }
  ).BarcodeDetector;
  if (!Detector) return null;
  const bitmap = await createImageBitmap(file);
  try {
    const found = await new Detector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] }).detect(bitmap);
    return found[0]?.rawValue ?? null;
  } finally {
    bitmap.close();
  }
}

export const canReadBarcodes = () => typeof globalThis !== "undefined" && "BarcodeDetector" in globalThis;
