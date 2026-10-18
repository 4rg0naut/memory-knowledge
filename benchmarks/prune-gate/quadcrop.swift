import Foundation
import AppKit

guard CommandLine.arguments.count > 1,
      let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write("usage: quadcrop <image> [outdir]\n".data(using: .utf8)!)
    exit(2)
}
let outdir = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "."
let w = cg.width, h = cg.height
let hw = w / 2, hh = h / 2
let rects = [
    CGRect(x: 0, y: 0, width: hw, height: hh),
    CGRect(x: hw, y: 0, width: w - hw, height: hh),
    CGRect(x: 0, y: hh, width: hw, height: h - hh),
    CGRect(x: hw, y: hh, width: w - hw, height: h - hh),
]
let base = (outdir as NSString).appendingPathComponent(
    ((CommandLine.arguments[1] as NSString).lastPathComponent as NSString).deletingPathExtension)
for (i, rect) in rects.enumerated() {
    let crop = cg.cropping(to: rect)!
    let rep = NSBitmapImageRep(cgImage: crop)
    let data = rep.representation(using: .png, properties: [:])!
    try! data.write(to: URL(fileURLWithPath: "\(base).q\(i + 1).png"))
    print("\(base).q\(i + 1).png")
}
