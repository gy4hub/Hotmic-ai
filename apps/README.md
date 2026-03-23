# Apps

`apps/` 是 HotMic AI 的规范运行目录。

- `superdirector/`: 选题、评分、框架、反馈闭环
- `script-creator/`: 9 件套脚本创作
- `review-engine/`: 复盘和 patch 生成
- `style-learner/`: 风格规则学习与维护
- `video-cutter/`: 视频粗剪
- `publish-kit/`: 平台发布包生成

根目录保留了 `superdirector`、`hotmic-*` 兼容链接，方便旧脚本继续使用，但新增开发默认都以 `apps/` 为准。

迁移标注:
- 规范路径示例: `apps/superdirector/main.py`
- 兼容路径示例: `superdirector/main.py`
- 提交代码、写 README、做 OpenClaw 接线时，请优先引用规范路径
