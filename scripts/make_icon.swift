// Renders the app icon with CoreGraphics: coral squircle, waveform bars with
// the middle (vocal) bars knocked back. Usage: swift make_icon.swift out.png
import AppKit
let size: CGFloat = 1024
let img = NSImage(size: NSSize(width: size, height: size))
img.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext
let inset: CGFloat = 100
let rect = CGRect(x: inset, y: inset, width: size - 2*inset, height: size - 2*inset)
let path = CGPath(roundedRect: rect, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: NSColor.black.withAlphaComponent(0.3).cgColor)
ctx.addPath(path); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState(); ctx.addPath(path); ctx.clip()
let colors = [NSColor(red: 1.0, green: 0.47, blue: 0.36, alpha: 1).cgColor,
              NSColor(red: 0.84, green: 0.24, blue: 0.22, alpha: 1).cgColor] as CFArray
let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 0, y: size - inset), end: CGPoint(x: 0, y: inset), options: [])
let heights: [CGFloat] = [0.18, 0.34, 0.52, 0.30, 0.62, 0.80, 0.56, 0.74, 0.40, 0.58, 0.32, 0.20]
let barW: CGFloat = 38, gap: CGFloat = 24
let total = CGFloat(heights.count) * barW + CGFloat(heights.count - 1) * gap
var x = (size - total) / 2
for (i, h) in heights.enumerated() {
    let bh = h * 520
    let bar = CGRect(x: x, y: size/2 - bh/2, width: barW, height: bh)
    let vocal = (4...7).contains(i)
    ctx.setFillColor(NSColor.white.withAlphaComponent(vocal ? 0.28 : 1).cgColor)
    ctx.addPath(CGPath(roundedRect: bar, cornerWidth: barW/2, cornerHeight: barW/2, transform: nil)); ctx.fillPath()
    x += barW + gap
}
ctx.restoreGState()
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
