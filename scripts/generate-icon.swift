#!/usr/bin/env swift
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let resources = root.appendingPathComponent("Resources")
let iconset = root.appendingPathComponent("build/CH348.iconset")
try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func color(_ hex: UInt32, alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: alpha)
}

func rounded(_ rect: NSRect, radius: CGFloat) -> NSBezierPath {
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
}

func drawIcon() {
    let board = rounded(NSRect(x: 80, y: 80, width: 864, height: 864), radius: 188)
    NSGraphicsContext.saveGraphicsState()
    let boardShadow = NSShadow()
    boardShadow.shadowColor = color(0x102C48, alpha: 0.28)
    boardShadow.shadowBlurRadius = 26
    boardShadow.shadowOffset = NSSize(width: 0, height: -12)
    boardShadow.set()
    color(0x183E61).setFill()
    board.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: color(0x153B5D), ending: color(0x287C9D))!.draw(in: board, angle: 90)
    color(0xFFFFFF, alpha: 0.22).setStroke()
    board.lineWidth = 2
    board.stroke()

    // Eight copper lanes terminate at four pads on each side of the UART chip.
    for y in stride(from: CGFloat(386), through: 638, by: 84) {
        for left in [true, false] {
            let padX: CGFloat = left ? 184 : 840
            let lane = NSBezierPath()
            lane.move(to: NSPoint(x: padX, y: y))
            lane.line(to: NSPoint(x: left ? 336 : 688, y: y))
            lane.lineWidth = 18
            lane.lineCapStyle = .round
            color(0xE4B275).setStroke()
            lane.stroke()
            let pad = NSBezierPath(ovalIn: NSRect(x: padX - 22, y: y - 22, width: 44, height: 44))
            color(0xF2CA90).setFill()
            pad.fill()
            let pin = rounded(NSRect(x: left ? 288 : 688, y: y - 19, width: 48, height: 38), radius: 8)
            NSGradient(starting: color(0xBD8B50), ending: color(0xF5D8A6))!.draw(in: pin, angle: 90)
        }
    }

    let chip = rounded(NSRect(x: 316, y: 304, width: 392, height: 416), radius: 58)
    NSGraphicsContext.saveGraphicsState()
    let chipShadow = NSShadow()
    chipShadow.shadowColor = color(0x092C46, alpha: 0.6)
    chipShadow.shadowBlurRadius = 22
    chipShadow.shadowOffset = NSSize(width: 0, height: -14)
    chipShadow.set()
    color(0x9EAFBE).setFill()
    chip.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: color(0xB7C8D6), ending: color(0xF0F5F8))!.draw(in: chip, angle: 90)
    color(0xFFFFFF, alpha: 0.8).setStroke()
    chip.lineWidth = 3
    chip.stroke()

    // A serial waveform remains recognizable when the icon is reduced to 16 pt.
    let signal = NSBezierPath()
    signal.move(to: NSPoint(x: 386, y: 490))
    for point in [NSPoint(x: 434, y: 490), NSPoint(x: 434, y: 572),
                  NSPoint(x: 502, y: 572), NSPoint(x: 502, y: 452),
                  NSPoint(x: 570, y: 452), NSPoint(x: 570, y: 534),
                  NSPoint(x: 638, y: 534)] {
        signal.line(to: point)
    }
    signal.lineWidth = 28
    signal.lineCapStyle = .round
    signal.lineJoinStyle = .round
    color(0x244C68).setStroke()
    signal.stroke()
    color(0x7F99AB).setFill()
    NSBezierPath(ovalIn: NSRect(x: 354, y: 648, width: 18, height: 18)).fill()
}

func png(size: Int) -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                  isPlanar: false, colorSpaceName: .deviceRGB,
                                  bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.clear(CGRect(x: 0, y: 0, width: size, height: size))
    let scale = CGFloat(size) / 1024
    context.cgContext.scaleBy(x: scale, y: scale)
    drawIcon()
    NSGraphicsContext.restoreGraphicsState()
    return bitmap.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try png(size: size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try png(size: size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
try png(size: 1024).write(to: resources.appendingPathComponent("CH348.png"))
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", iconset.path, "-o", resources.appendingPathComponent("CH348.icns").path]
try process.run()
process.waitUntilExit()
if process.terminationStatus != 0 { exit(process.terminationStatus) }
print("Wrote Resources/CH348.icns and Resources/CH348.png")
