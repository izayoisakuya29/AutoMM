"""构建整题最终研究摘要，不承担论文写作。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import (
    ROOT,
    config_section,
    read_yaml,
    relative,
    resolve_project_path,
    utc_now,
    write_json,
    write_text,
)
from .problems import load_problem, problem_dir, question_manifest
from .tasks import list_tasks


_LEDGER_PATH = ROOT / "reports" / "autoresearch" / "experiment_ledger.md"
_LEDGER_SEPARATOR = re.compile(r"^\|?[\s:|-]+\|?$")
_LEDGER_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _clean_ledger_cell(value: str) -> str:
    return value.replace("\\|", "|").replace("<br>", "\n").strip()


def _latest_ledger_conclusion(question_id: str) -> str:
    """从实验账本中取该小问最后一条非空 conclusion。"""
    if not _LEDGER_PATH.is_file():
        return ""
    latest = ""
    for line in _LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or _LEDGER_SEPARATOR.match(line):
            continue
        cells = [_clean_ledger_cell(item) for item in _LEDGER_CELL_SPLIT.split(line)[1:-1]]
        if len(cells) < 9 or cells[0] == "日期":
            continue
        question = cells[1]
        if question == question_id or question.startswith(f"{question_id} "):
            if cells[7]:
                latest = cells[7]
    return latest


def _format_key_assumptions(version: dict[str, Any]) -> list[str]:
    assumptions = [item for item in version.get("assumptions", []) if isinstance(item, dict)]
    key_assumptions = [item for item in assumptions if item.get("key")] or assumptions
    lines = []
    for item in key_assumptions[:8]:
        name = str(item.get("name") or item.get("id") or "假设").strip()
        statement = str(item.get("statement") or "").strip()
        if statement:
            lines.append(f"- **{name}**：{statement}")
    return lines


def _ensure_question_summary(
    problem_id: str,
    question_id: str,
    manifest: dict[str, Any],
) -> Path | None:
    """为缺少或仍是占位符的小问总结生成确定性归档文本。"""
    accepted = int(manifest.get("accepted_assumption_version", 0))
    if accepted < 1:
        return None
    version_name = f"assumption_v{accepted:03d}"
    version_dir = problem_dir(problem_id) / question_id / "versions" / version_name
    if not version_dir.is_dir():
        return None
    summary_path = version_dir / "question_summary.md"
    if summary_path.is_file():
        existing = summary_path.read_text(encoding="utf-8").strip()
        if existing and "待填写" not in existing:
            return summary_path

    version = read_yaml(version_dir / "version.yaml", {})
    conclusion = _latest_ledger_conclusion(question_id)
    optional = manifest.get("optional_stages", {}) or {}
    sanity = manifest.get("sanity", {}) or {}
    conclusion_meta = manifest.get("conclusion", {}) or {}
    lines = [
        f"# {question_id} 小问总结",
        "",
        "> 本摘要由 AutoMM 根据既有 manifest、版本产物和实验账本自动整理；未新增或编造结论。",
        "",
        "## 完成状态",
        "",
        f"- 接受假设版本：`{version_name}`",
        f"- 接受公式版本：`formulation_v{int(manifest.get('accepted_formulation_version', 0)):03d}`",
        f"- 结论标识：`{conclusion_meta.get('conclusion_id', '')}`"
        f"（version {conclusion_meta.get('version', 0)}，hash `{conclusion_meta.get('content_hash', '')}`）",
        f"- Sanity：L1-L4={sanity.get('level_1_4')}，L5={sanity.get('level_5')}，L6={sanity.get('level_6')}",
        f"- 鲁棒性：{optional.get('robustness', {}).get('decision', 'pending') if isinstance(optional.get('robustness'), dict) else 'pending'}",
        f"- 消融：{optional.get('ablation', {}).get('decision', 'pending') if isinstance(optional.get('ablation'), dict) else 'pending'}",
        "",
    ]
    assumptions = _format_key_assumptions(version)
    if assumptions:
        lines += ["## 关键假设", "", *assumptions, ""]
    if conclusion:
        lines += ["## 最终结论", "", conclusion, ""]
    else:
        fallback = []
        for stage in ("robustness", "ablation"):
            item = optional.get(stage) or {}
            if isinstance(item, dict) and item.get("reason"):
                fallback.append(f"- {stage}：{item['reason']}")
        if fallback:
            lines += ["## 已记录的实验结论", "", *fallback, ""]
    history = [item for item in manifest.get("sanity_history", []) if isinstance(item, dict)]
    if history:
        lines += ["## Sanity 记录", ""]
        for item in history[-4:]:
            lines.append(f"- {item.get('level')} {item.get('status')}：{item.get('reason', '')}")
        lines.append("")
    for stage, title in (("robustness", "鲁棒性与敏感性"), ("ablation", "消融实验")):
        item = optional.get(stage) or {}
        reason = item.get("reason") if isinstance(item, dict) else ""
        if reason:
            lines += [f"## {title}", "", str(reason), ""]
    lines += ["## 产物", "", f"- 版本目录：`{relative(version_dir)}`", ""]
    write_text(summary_path, "\n".join(lines).rstrip() + "\n")
    return summary_path


def build_final_summary(problem_id: str) -> dict[str, Any]:
    config = config_section("summary", problem_id)
    problem = load_problem(problem_id)
    if config.get("require_cross_question_review", True) and problem.get("cross_question_review") != "passed":
        raise RuntimeError("跨小问审查未通过，不能生成最终摘要")
    sections = []
    errors: list[str] = []
    tasks = list_tasks()
    figures = read_yaml(problem_dir(problem_id) / "figures.yaml", {"figures": []}).get("figures", [])
    citations = read_yaml(problem_dir(problem_id) / "citations.yaml", {"references": []}).get("references", [])
    for question_id in problem["questions"]:
        _, manifest = question_manifest(problem_id, question_id)
        if manifest.get("stage") != "locally_completed":
            errors.append(f"{question_id} 尚未 locally_completed")
            continue
        accepted = int(manifest.get("accepted_assumption_version", 0))
        version_name = f"assumption_v{accepted:03d}"
        version_dir = problem_dir(problem_id) / question_id / "versions" / version_name
        summary_path = _ensure_question_summary(problem_id, question_id, manifest) or (
            version_dir / "question_summary.md"
        )
        if not summary_path.is_file():
            errors.append(f"{question_id} 缺少 question_summary.md")
            continue
        text = summary_path.read_text(encoding="utf-8").strip()
        if not text or "待填写" in text:
            errors.append(f"{question_id} 的 question_summary.md 仍为空")
        question_tasks = [
            item for item in tasks if item.get("problem_id") == problem_id and item.get("question_id") == question_id
        ]
        question_figures = [
            item
            for item in figures
            if item.get("question_id") == question_id
            and item.get("assumption_version") == version_name
            and item.get("included_in_summary", True)
        ]
        task_lines = "- 配置为不收录任务追踪"
        if config.get("include_task_trace", True):
            task_lines = (
                "\n".join(
                    f"- `{item.get('task_id')}`：{item.get('status')}，阶段 `{item.get('stage')}`"
                    for item in question_tasks
                )
                or "- 无登记计算任务"
            )
        figure_lines = "- 配置为不收录图表索引"
        if config.get("include_figures", True):
            figure_lines = (
                "\n".join(
                    f"- `{item.get('stable_id')}`：{item.get('title')}，`{item.get('path')}`"
                    for item in question_figures
                )
                or "- 无登记图表"
            )
        optional = manifest.get("optional_stages", {})
        sections.append(f"""## {question_id}

- 接受假设版本：`{version_name}`
- 接受公式版本：`formulation_v{int(manifest.get("accepted_formulation_version", 0)):03d}`
- L1-L4 sanity：{manifest.get("sanity", {}).get("level_1_4")}
- L5 sanity：{manifest.get("sanity", {}).get("level_5")}
- 鲁棒性：{optional.get("robustness", {})}
- 消融：{optional.get("ablation", {})}

### 小问总结

{text}

### 任务追踪

{task_lines}

### 图表索引

{figure_lines}
""")
    if errors:
        raise RuntimeError("最终摘要门禁未通过：" + "；".join(errors))
    citation_lines = "- 配置为不收录文献索引"
    if config.get("include_citations", True):
        citation_lines = (
            "\n".join(
                f"- `{item.get('id', '?')}`：{item.get('title', '')}，"
                f"{item.get('source', '')}（{item.get('year', '')}）"
                for item in citations
            )
            or "- 无登记文献"
        )
    output = resolve_project_path(config.get("output", "reports/final_summary.md"))
    content = f"""# {problem_id} 最终研究摘要

- 生成时间：{utc_now()}
- 小问数量：{len(problem["questions"])}
- 跨小问审查：{problem.get("cross_question_review")}
- 本文件是研究结果归档，不是比赛论文。

{chr(10).join(sections)}

## 跨小问一致性

{problem.get("cross_question_review_reason", "已通过，未记录补充说明。")}

## 文献索引

{citation_lines}
"""
    archive = resolve_project_path(
        str(config.get("archive_output_template", "reports/problems/{problem_id}/final_summary.md")).format(
            problem_id=problem_id
        )
    )
    if archive.exists():
        content = archive.read_text(encoding="utf-8")
    else:
        write_text(archive, content)
    write_text(output, content)
    problem["summary_status"] = "built"
    problem["summary_path"] = relative(output)
    problem["summary_archive_path"] = relative(archive)
    problem["summary_built_at"] = utc_now()
    write_json(problem_dir(problem_id) / "problem_state.json", problem)
    return {
        "problem_id": problem_id,
        "summary": relative(output),
        "archive": relative(archive),
        "questions": len(problem["questions"]),
    }
