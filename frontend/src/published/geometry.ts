import type { PageGeometry, PdfRectangle } from './generated'

export interface Viewport { width: number; height: number; convertToViewportPoint(x: number, y: number): number[] }
export interface Highlight { left: number; top: number; width: number; height: number }

export function geometryMatches(geometry: PageGeometry, view: readonly number[], rotation: number): boolean {
  const crop = geometry.crop_box
  return view.length === 4 && [crop.x0, crop.y0, crop.x1, crop.y1].every((value, index) => Math.abs(value - (view[index] ?? Infinity)) < 0.01) && ((rotation % 360) + 360) % 360 === geometry.rotation
}

export function highlightBox(box: PdfRectangle, viewport: Viewport): Highlight | null {
  const coordinates = [...viewport.convertToViewportPoint(box.x0, box.y0), ...viewport.convertToViewportPoint(box.x1, box.y1)]
  const [x0, y0, x1, y1] = coordinates
  if (x0 === undefined || y0 === undefined || x1 === undefined || y1 === undefined || !coordinates.every(Number.isFinite)) return null
  const left = Math.max(0, Math.min(x0, x1)); const top = Math.max(0, Math.min(y0, y1))
  const width = Math.min(viewport.width, Math.max(x0, x1)) - left
  const height = Math.min(viewport.height, Math.max(y0, y1)) - top
  return width > 0 && height > 0 ? { left, top, width, height } : null
}
