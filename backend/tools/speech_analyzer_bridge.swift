#!/usr/bin/env swift

import Foundation
import Speech
import AVFoundation

@available(macOS 26.0, *)
func transcribeAudioFile(audioPath: String) async throws -> String {
    let fileURL = URL(fileURLWithPath: audioPath)

    // 检查文件是否存在
    guard FileManager.default.fileExists(atPath: audioPath) else {
        throw NSError(domain: "SpeechAnalyzer", code: 1, userInfo: [NSLocalizedDescriptionKey: "Audio file not found: \(audioPath)"])
    }

    // 设置语言（中文）
    let locale = Locale(identifier: "zh-CN")

    // 创建SpeechTranscriber模块（使用完整的初始化参数）
    let transcriber = SpeechTranscriber(
        locale: locale,
        transcriptionOptions: [],
        reportingOptions: [.volatileResults, .fastResults],
        attributeOptions: []
    )

    // 创建SpeechAnalyzer
    let analyzer = SpeechAnalyzer(modules: [transcriber])

    // 创建音频文件对象
    let audioFile = try AVAudioFile(forReading: fileURL)

    // 开始分析音频文件（async方法）
    try await analyzer.start(inputAudioFile: audioFile, finishAfterFile: true)

    // 准备分析参数
    var finalTranscript: String = ""

    // 从transcriber获取结果
    for try await result in transcriber.results {
        // 只收集最终结果
        if result.isFinal {
            let text = String(result.text.characters)
            finalTranscript += text + " "
        }
    }

    return finalTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
}

// 命令行接口
if CommandLine.arguments.count < 2 {
    fputs("Usage: speech_analyzer_bridge <audio_path>\n", stderr)
    exit(1)
}

let audioPath = CommandLine.arguments[1]

if #available(macOS 26.0, *) {
    Task {
        do {
            let result = try await transcribeAudioFile(audioPath: audioPath)
            print(result)
            exit(0)
        } catch {
            fputs("Error: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    // 保持运行直到异步任务完成
    RunLoop.current.run()
} else {
    fputs("Error: This tool requires macOS 26.0 or later\n", stderr)
    exit(1)
}
