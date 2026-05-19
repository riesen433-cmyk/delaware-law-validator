# Delaware Law Validator — Adversarial Testing Harness

全自动对抗测试框架，用于批量生成、运行、评估 Delaware 法律引用校验测试。

## 快速开始

```bash
cd adversarial_tests
python run_all.py
```

这会依序执行：mutator → runner → evaluator → reporter，最后在终端输出汇总结果。

## 目录结构

```
adversarial_tests/
  README.md              # 本文件
  config.json            # 配置文件
  run_all.py             # 一键运行全流程
  runner.py              # CLI 调用与输出捕获
  evaluator.py           # 预期 vs 实际比对引擎
  reporter.py            # Markdown 报告生成
  mutator.py             # 格式变体批量生成
  cases/                 # 手写测试用例
    round_001_basic.json
    round_002_format_variants.json
    round_003_topic_mismatch.json
    round_004_coverage_boundary.json
    round_005_semantic_traps.json
  generated/             # mutator 生成的变体用例
  results/               # 实际输出 + 评估结果
  reports/               # Markdown 报告
```

## 配置

编辑 `config.json`：

```json
{
  "validator_cmd": "delaware-law",
  "default_mode": "validate",
  "timeout_seconds": 30,
  "case_glob": "cases/*.json",
  "generated_case_glob": "generated/*.json",
  "results_dir": "results",
  "reports_dir": "reports",
  "run_generated_cases": true,
  "normalize_unicode": true
}
```

### validator_cmd 配置

如果 `delaware-law` 命令不在 PATH 中，请修改 `validator_cmd` 为实际可执行路径。常见选项：

- 如果已通过 `pip install -e .` 安装：`"validator_cmd": "delaware-law"`
- 直接用 Python 运行：`"validator_cmd": "python -m delaware_law_skill.cli"`
- 指定完整路径：`"validator_cmd": "/path/to/python -m delaware_law_skill.cli"`

**注意**：runner.py 使用 `subprocess.run([cmd, ...])` 调用，不支持 shell 管道。如果 validator_cmd 包含空格（如 `python -m ...`），runner 会自动拆分为列表。

如果 validator_cmd 配置的路径不存在，runner 会打印警告，所有 case 会标记为 `unexpected_cli_error`，但不会中断流程。

### 只跑手写 cases

将 `"run_generated_cases": false` 即可跳过 mutator 生成的变体用例。

## 新增测试用例

在 `cases/` 目录下新建 JSON 文件，遵守以下 schema：

```json
[
  {
    "id": "round_NNN_case_NNN",
    "title": "用例标题",
    "category": "basic_validation | topic_mismatch | coverage_boundary | ...",
    "mode": "validate",
    "text": "包含法律引用的待校验文本...",
    "expected": {
      "citations_detected": ["6 Del. C. § 17-407"],
      "should_pass": [
        {
          "citation": "6 Del. C. § 17-407",
          "reason": "该引用应被正确识别并验证通过。"
        }
      ],
      "should_error": [
        {
          "citation": "6 Del. C. § 17-170",
          "reason": "错误的条文编号。"
        }
      ],
      "should_warn": [
        {
          "type": "topic_mismatch",
          "contains_any": ["topic mismatch", "主题可能不匹配"],
          "reason": "预期提示主题不匹配。"
        }
      ],
      "coverage_warnings": [
        {
          "citation": "5 U.S.C. § 552",
          "contains_any": ["federal", "not covered"]
        }
      ],
      "must_not_contain": ["Traceback", "Unhandled exception"]
    }
  }
]
```

`expected` 中的所有字段均为 optional，evaluator 不会因为字段缺失而崩溃。

## 失败类型说明

| 类型 | 含义 |
|---|---|
| `missed_citation` | 预期应检测到的引用未在输出中出现 |
| `false_positive` | 对一个正确的引用输出了错误/不匹配信号 |
| `false_negative` | 对一个错误的引用未输出错误/不匹配信号 |
| `parse_failure` | 引用解析失败 |
| `topic_mismatch_missing` | 应提示主题不匹配但未提示 |
| `coverage_warning_missing` | 应提示覆盖边界但未提示 |
| `wrong_suggestion` | 建议了错误的替代条文 |
| `unexpected_cli_error` | CLI 异常（超时、崩溃、命令不存在等） |

## Citation Normalization

evaluator 的 `normalize_citation()` 函数会尝试将以下格式视为等价：

- `6 Del. C. § 17-407`
- `6 Del.C. §17-407`
- `6 Del C § 17-407`
- `Title 6, Section 17-407`
- `Section 17-407 of Title 6`
- `6 Del. C. ch. 17`
- `Title 6, Chapter 17`

规范化处理包括：Unicode NFKC、多余空格合并、`Del.C.` / `Del C` / `Del. C.` 统一、`ch.` / `chapter` / `Chapter` 统一、尾随标点去除。

这不是完美的 NLP，但在大多数格式变体场景下足够使用。

## 运行前提

- Python >= 3.10
- Delaware Law Validator 已安装且 `validator_cmd` 配置正确

## 重要说明

当前 evaluator 采用启发式（heuristic）关键词匹配，不等于最终法律判断。以下情况需要人工复核：

- 边界条件 case（如正确引用但包含部分"不匹配"关键词）
- 格式变体 case（某些变体可能合法但 evaluator 未规范化处理）
- 中文关键词匹配（`主题可能不匹配` 等依赖于 validator 输出中文消息）

定期审查 `reports/latest.md` 中的 FAIL 项，确认哪些是真正的工具缺陷，哪些是 evaluator 自身的局限性。
