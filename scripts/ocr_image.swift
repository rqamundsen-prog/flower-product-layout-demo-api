import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count >= 2 else {
    fputs("usage: ocr_image.swift <image-path>\n", stderr)
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL) else {
    fputs("unable to load image\n", stderr)
    exit(3)
}

var proposedRect = CGRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
    fputs("unable to create CGImage\n", stderr)
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
request.minimumTextHeight = 0.004

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("ocr failed: \(error)\n", stderr)
    exit(5)
}

let observations = request.results ?? []
let lines = observations.compactMap { observation in
    observation.topCandidates(1).first?.string.trimmingCharacters(in: .whitespacesAndNewlines)
}.filter { !$0.isEmpty }

print(lines.joined(separator: "\n"))
