# 剪辑规则说明文档

## 重复段落检测规则

### 脚本对齐模式（有脚本时使用）

1. **脚本句拆分**：以句号、问号、感叹号、换行为分隔符，将定稿脚本拆为独立句子
2. **转录段匹配**：对每个脚本句，遍历所有转录segment，计算编辑距离相似度
3. **重复判定**：一个脚本句匹配到N个转录段（N>1）→ 判定为重复录制

### 无脚本模式（无脚本时的fallback）

- 相邻segment之间计算字符级n-gram余弦相似度
- 相似度 > 0.85 → 判定为重复
- 保留时长更长或完整度更高的版本

---

## 重复段选优算法

对每组重复段，计算综合评分，保留得分最高的段：

| 指标 | 权重 | 计算方式 |
|------|------|----------|
| 与原稿编辑距离（越低越好） | 0.6 | `1 - normalized_levenshtein(segment_text, script_sentence)` |
| 流利度（越高越好） | 0.4 | `1 / (pause_count + word_gap_std + 1)` |

**综合分 = 0.6 × 文本准确度 + 0.4 × 流利度**

---

## 静音处理规则

| 情况 | 处理方式 |
|------|----------|
| 静音时长 ≤ 0.3秒 | 保留（自然停顿） |
| 静音时长 0.3s–0.8s | 保留（合理停顿） |
| 静音时长 > 0.8秒 | 压缩为0.3秒 |

静音检测基于Whisper word级时间戳的间隔计算：
- 相邻word之间的时间间隔 > 0.8s → 判定为静音段

---

## FFmpeg剪辑方式

使用 `filter_complex` 的 `concat` 滤镜无损剪辑，保留所有视频/音频轨道：

```
ffmpeg -i input.MOV \
  -filter_complex "[0:v]trim=start=T1:end=T2,setpts=PTS-STARTPTS[v1];
                   [0:a]atrim=start=T1:end=T2,asetpts=PTS-STARTPTS[a1];
                   ...
                   [v1][a1][v2][a2]...concat=n=N:v=1:a=1[vout][aout]" \
  -map "[vout]" -map "[aout]" \
  -c:v libx264 -preset fast -crf 18 \
  output.mp4
```

---

## 注意事项

1. Groq Whisper免费层限制：单文件 ≤ 25MB。口播音频约3-5MB，正常使用无需担心。
2. 脚本对齐精度取决于脚本与实际口播的一致程度。如果口播时大幅改词，建议使用无脚本模式。
3. 建议在执行 `execute_cut.py` 前，先查阅 `cut_report.md` 人工确认删除决策无误。
