import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1,
      let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write("usage: vision_ocr <image>\n".data(using: .utf8)!)
    exit(2)
}

let sem = DispatchSemaphore(value: 0)
var out = ""
let request = VNRecognizeTextRequest { req, _ in
    let lines = (req.results as? [VNRecognizedTextObservation] ?? [])
        .compactMap { $0.topCandidates(1).first?.string }
    out = lines.joined(separator: "\n")
    sem.signal()
}
request.recognitionLevel = .accurate
let session = VNImageRequestHandler(cgImage: cg, options: [:])
do { try session.perform([request]) } catch {
    FileHandle.standardError.write("ocr failed: \(error)\n".data(using: .utf8)!)
    exit(1)
}
sem.wait()
print(out)
