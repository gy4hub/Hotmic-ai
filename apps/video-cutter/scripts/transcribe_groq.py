#!/usr/bin/env python3
"""
transcribe_groq.py — Step 2: 调用Groq Whisper API转录音频

使用 whisper-large-v3 模型，返回含word+segment级别时间戳的verbose_json。

用法:
  python transcribe_groq.py --input audio.wav --output transcript.json
  python transcribe_groq.py --input audio.wav --output transcript.json --language zh
"""

import argparse
import json
import os
import sys
from pathlib import Path


def transcribe(input_path: str, output_path: str, language: str = "zh") -> dict:
    """
    调用Groq Whisper API转录音频文件。

    Args:
        input_path: 输入WAV文件路径
        output_path: 输出JSON文件路径
        language: 语言代码（默认zh）

    Returns:
        转录结果字典

    Raises:
        FileNotFoundError: 输入文件不存在
        EnvironmentError: GROQ_API_KEY未设置
        RuntimeError: API调用失败
    """
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError(
            "groq包未安装。请运行: pip install groq\n"
            "或执行: bash scripts/install_deps.sh"
        )

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {input_path}")

    # 验证API Key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY 环境变量未设置。\n"
            "请运行: export GROQ_API_KEY=your_key_here"
        )

    # 文件大小检查（Groq免费层限制25MB）
    file_size_mb = input_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 25:
        raise RuntimeError(
            f"文件 {file_size_mb:.1f}MB 超过Groq免费层25MB限制。"
            "请先对视频分段处理。"
        )

    print(f"[INFO] 正在转录: {input_path} ({file_size_mb:.1f}MB)")
    print(f"[INFO] 语言: {language}, 模型: whisper-large-v3")

    client = Groq(api_key=api_key)

    with open(input_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language=language
        )

    # 转换为可序列化的字典
    result = {
        "text": transcription.text,
        "language": transcription.language if hasattr(transcription, 'language') else language,
        "duration": transcription.duration if hasattr(transcription, 'duration') else None,
        "segments": [],
        "words": []
    }

    # 处理segments
    if hasattr(transcription, 'segments') and transcription.segments:
        for seg in transcription.segments:
            result["segments"].append({
                "id": seg.id if hasattr(seg, 'id') else None,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "avg_logprob": seg.avg_logprob if hasattr(seg, 'avg_logprob') else None,
                "no_speech_prob": seg.no_speech_prob if hasattr(seg, 'no_speech_prob') else None
            })

    # 处理words
    if hasattr(transcription, 'words') and transcription.words:
        for word in transcription.words:
            result["words"].append({
                "word": word.word.strip(),
                "start": word.start,
                "end": word.end
            })

    # 保存结果
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    seg_count = len(result["segments"])
    word_count = len(result["words"])
    print(f"[OK] 转录完成: {seg_count}段, {word_count}词")
    print(f"[OK] 保存到: {output_path}")
    print(f"[INFO] 完整文本预览: {result['text'][:100]}...")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="使用Groq Whisper API转录音频（输出含时间戳的verbose_json）"
    )
    parser.add_argument("--input", "-i", required=True, help="输入WAV文件路径")
    parser.add_argument("--output", "-o", default="transcript.json", help="输出JSON文件路径")
    parser.add_argument("--language", "-l", default="zh", help="语言代码（默认: zh）")
    args = parser.parse_args()

    try:
        transcribe(args.input, args.output, args.language)
    except (FileNotFoundError, EnvironmentError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
