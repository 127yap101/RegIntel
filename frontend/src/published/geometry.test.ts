import { describe, expect, it } from 'vitest'
import { geometryMatches, highlightBox } from './geometry'
import { decode } from './api'
import fixtures from './fixtures.generated.json'

describe('unrotated PDF-point evidence regions', () => {
  const geometry = decode('evidence', fixtures.evidence).evidence.record.page_geometry
  it('requires matching crop coordinates and rotation before overlaying anything', () => {
    expect(geometryMatches(geometry, [0, 0, 612, 792], 0)).toBe(true)
    expect(geometryMatches(geometry, [10, 20, 602, 772], 0)).toBe(false)
    expect(geometryMatches(geometry, [0, 0, 612, 792], 90)).toBe(false)
  })
  it('maps bottom-left coordinates through the actual viewport transform', () => {
    const result = highlightBox({ x0: 50, y0: 698, x1: 400, y1: 711 }, { width: 612, height: 792, convertToViewportPoint: (x, y) => [x, 792-y] })
    expect(result).toEqual({ left: 50, top: 81, width: 350, height: 13 })
  })
  it('handles an offset crop and quarter-turn without applying rotation twice', () => {
    const cropped = { ...geometry, crop_box: { x0: 10, y0: 20, x1: 602, y1: 772 }, rotation: 90 as const }
    expect(geometryMatches(cropped, [10, 20, 602, 772], 90)).toBe(true)
    expect(highlightBox({ x0: 30, y0: 40, x1: 60, y1: 80 }, { width: 752, height: 592, convertToViewportPoint: (x, y) => [y-20, x-10] })).toEqual({ left: 20, top: 20, width: 40, height: 30 })
  })
  it('clips invisible regions and rejects nonfinite transforms', () => {
    const box = { x0: -10, y0: -20, x1: 15, y1: 10 }
    expect(highlightBox(box, { width: 100, height: 100, convertToViewportPoint: (x, y) => [x, y] })).toEqual({ left: 0, top: 0, width: 15, height: 10 })
    expect(highlightBox(box, { width: 100, height: 100, convertToViewportPoint: () => [Infinity, 0] })).toBeNull()
  })
  it.each([180, 270] as const)('maps an offset crop at %s degrees', (rotation) => {
    const geometryAtAngle = { ...geometry, crop_box: { x0: 10, y0: 20, x1: 602, y1: 772 }, rotation }
    expect(geometryMatches(geometryAtAngle, [10, 20, 602, 772], rotation)).toBe(true)
    const viewport = rotation === 180
      ? { width: 592, height: 752, convertToViewportPoint: (x: number, y: number) => [602-x, y-20] }
      : { width: 752, height: 592, convertToViewportPoint: (x: number, y: number) => [772-y, 602-x] }
    expect(highlightBox({ x0: 30, y0: 40, x1: 60, y1: 80 }, viewport)).toEqual(rotation === 180 ? { left: 542, top: 20, width: 30, height: 40 } : { left: 692, top: 542, width: 40, height: 30 })
  })
})
