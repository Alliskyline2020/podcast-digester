#!/bin/bash
# 编译Apple SpeechAnalyzer桥接工具

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWIFT_FILE="$SCRIPT_DIR/speech_analyzer_bridge.swift"
OUTPUT_DIR="$SCRIPT_DIR/../app"
OUTPUT="$OUTPUT_DIR/speech_analyzer_bridge"

echo "🔨 Compiling Apple SpeechAnalyzer bridge tool..."

# 编译Swift工具（按本机架构构建：Apple Silicon→arm64，Intel→x86_64）
ARCH="$(uname -m)"
swiftc -o "$OUTPUT" "$SWIFT_FILE" \
    -framework Foundation \
    -framework Speech \
    -framework AVFoundation \
    -target "${ARCH}-apple-macosx26.0" \
    -Osize

if [ $? -eq 0 ]; then
    echo "✅ Successfully compiled: $OUTPUT"
    chmod +x "$OUTPUT"
else
    echo "❌ Compilation failed"
    exit 1
fi
