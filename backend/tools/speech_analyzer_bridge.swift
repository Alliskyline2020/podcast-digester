#!/usr/bin/env swift
//
// speech_analyzer_bridge.swift
//
// Apple macOS 26 SpeechAnalyzer 桥接：本地 ASR 转录，输出带时间戳的 JSON。
//
// 输出格式（stdout，一个 JSON 数组）：
//   [{"text": "...", "start_ms": 1234, "end_ms": 5678}, ...]
//
// 时间戳来自 SpeechTranscriber.Result.text 的 audioTimeRange 属性
// （attributeOptions: [.audioTimeRange]）。每个 AttributedString.run 携带
// 自己的时间区间，按 run 切分即可得到带时间戳的细粒度 segment。
//
// 用法：speech_analyzer_bridge <audio_path> [locale]
//   locale 默认 "zh-CN"（可传 "en-US" / "zh-CN" 等；AFM 对部分音频会自动检测）

import Foundation
import Speech
import AVFoundation
import CoreMedia

@available(macOS 26.0, *)
func transcribeAudioFile(audioPath: String, localeIdentifier: String) async throws -> String {
    let fileURL = URL(fileURLWithPath: audioPath)

    guard FileManager.default.fileExists(atPath: audioPath) else {
        throw NSError(domain: "SpeechAnalyzer", code: 1, userInfo: [NSLocalizedDescriptionKey: "Audio file not found: \(audioPath)"])
    }

    let locale = Locale(identifier: localeIdentifier)

    // attributeOptions 启用 audioTimeRange → result.text 的每个 run 带时间区间。
    // 去掉 .fastResults（要准确）；保留 .volatileResults 让 progressive refinement 生效，
    // 只在 isFinal 时收集。
    let transcriber = SpeechTranscriber(
        locale: locale,
        transcriptionOptions: [],
        reportingOptions: [.volatileResults],
        attributeOptions: [.audioTimeRange]
    )

    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let audioFile = try AVAudioFile(forReading: fileURL)

    try await analyzer.start(inputAudioFile: audioFile, finishAfterFile: true)

    struct Segment: Codable {
        let text: String
        let start_ms: Int
        let end_ms: Int
    }

    var segments: [Segment] = []

    for try await result in transcriber.results {
        guard result.isFinal else { continue }

        // 每个 final result 是一个 phrase。取整段文本 + 首词 start ~ 尾词 end 的时间范围，
        // 避免单词级 granularity（173min 音频会变成几万段，下游 LLM 处理太碎）。
        let attrText: AttributedString = result.text
        let phraseText = String(attrText.characters).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !phraseText.isEmpty else { continue }

        // 注意：直接 run.characters 会被 Runs.Element 的 @dynamicMemberLookup 截获，
        // 用 run.range 切片原始 AttributedString 再取 audioTimeRange。
        let runs = Array(attrText.runs)
        var startMs = 0
        var endMs = 0
        if let firstRange = runs.first?.audioTimeRange {
            startMs = Int(CMTimeGetSeconds(firstRange.start) * 1000)
        }
        if let lastRange = runs.last?.audioTimeRange {
            endMs = Int((CMTimeGetSeconds(lastRange.start) + CMTimeGetSeconds(lastRange.duration)) * 1000)
        }
        // 兜底：若 end 未取到，用 start
        if endMs <= startMs { endMs = startMs }

        segments.append(Segment(text: phraseText, start_ms: startMs, end_ms: endMs))
    }

    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted]
    let data = try encoder.encode(segments)
    return String(data: data, encoding: .utf8) ?? "[]"
}

// ===== 命令行入口 =====
if CommandLine.arguments.count < 2 {
    fputs("Usage: speech_analyzer_bridge <audio_path> [locale]\n", stderr)
    exit(1)
}

let audioPath = CommandLine.arguments[1]
let localeArg = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : "zh-CN"

if #available(macOS 26.0, *) {
    Task {
        do {
            let result = try await transcribeAudioFile(audioPath: audioPath, localeIdentifier: localeArg)
            print(result)
            exit(0)
        } catch {
            fputs("Error: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    RunLoop.current.run()
} else {
    fputs("Error: This tool requires macOS 26.0 or later\n", stderr)
    exit(1)
}
