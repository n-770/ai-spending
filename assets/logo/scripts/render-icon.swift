import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// Native Core Graphics transcription of the approved SVG. Refuse to render a
// changed source until this transcription is reviewed and updated as well.
let expected = """
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 120 120">
<rect width="120" height="120" rx="25" fill="#162336"/>
<path d="M27 82 A38 38 0 1 1 93 82" fill="none" stroke="#57E0B5" stroke-width="10" stroke-linecap="round"/>
<path d="M53 71 L79 42 L65 77 Z" fill="#57E0B5"/>
<circle cx="60" cy="73" r="7" fill="#57E0B5"/>
</svg>
"""
let args = CommandLine.arguments
precondition(args.count == 3, "usage: render-icon.swift source.svg output.iconset")
let source = try String(contentsOfFile: args[1], encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
precondition(source == expected, "approved SVG changed; update and review the renderer")
let output = URL(fileURLWithPath: args[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let files: [(String, Int)] = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024)
]
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let navy = CGColor(colorSpace: space, components: [22/255, 35/255, 54/255, 1])!
let mint = CGColor(colorSpace: space, components: [87/255, 224/255, 181/255, 1])!
for (name, size) in files {
    guard let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                              bytesPerRow: size * 4, space: space,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { fatalError("bitmap") }
    ctx.clear(CGRect(x: 0, y: 0, width: size, height: size))
    ctx.scaleBy(x: CGFloat(size) / 120, y: CGFloat(size) / 120)
    ctx.setFillColor(navy)
    ctx.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: 120, height: 120), cornerWidth: 25, cornerHeight: 25, transform: nil))
    ctx.fillPath()
    // Match SVG's downward-positive y coordinates.
    ctx.translateBy(x: 0, y: 120)
    ctx.scaleBy(x: 1, y: -1)
    ctx.setStrokeColor(mint)
    ctx.setLineWidth(10)
    ctx.setLineCap(.round)
    let cy = 82.0 - sqrt(38.0 * 38.0 - 33.0 * 33.0)
    let start = atan2(82.0 - cy, -33.0)
    let end = atan2(82.0 - cy, 33.0)
    ctx.addArc(center: CGPoint(x: 60, y: cy), radius: 38, startAngle: start, endAngle: end, clockwise: false)
    ctx.strokePath()
    ctx.setFillColor(mint)
    ctx.move(to: CGPoint(x: 53, y: 71))
    ctx.addLine(to: CGPoint(x: 79, y: 42))
    ctx.addLine(to: CGPoint(x: 65, y: 77))
    ctx.closePath()
    ctx.fillPath()
    ctx.fillEllipse(in: CGRect(x: 53, y: 66, width: 14, height: 14))
    guard let image = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(output.appendingPathComponent(name) as CFURL, UTType.png.identifier as CFString, 1, nil) else { fatalError("PNG destination") }
    CGImageDestinationAddImage(dest, image, nil)
    precondition(CGImageDestinationFinalize(dest), "PNG write failed")
}
