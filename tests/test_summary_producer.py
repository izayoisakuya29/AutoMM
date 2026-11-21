from __future__ import annotations

from pathlib import Path

import pytest

from automm.common import read_yaml, write_json, write_yaml
from automm.problems import create_assumption_version, load_problem, problem_dir, question_manifest
from automm.summary import build_final_summary

pytestmark = pytest.mark.integration


def test_final_summary_generates_missing_question_summaries(
    initialized_problem: tuple[str, Path],
    project_root: Path,
) -> None:
    problem_id, _ = initialized_problem
    problem = load_problem(problem_id)
    ledger_path = project_root / "reports" / "autoresearch" / "experiment_ledger.md"
    ledger_rows = [
        "# 建模实验账本",
        "",
        "| 日期 | question | stage | hypothesis | setup | result | sanity | conclusion | next |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for question_id in problem["questions"]:
        version_dir = create_assumption_version(problem_id, question_id)
        version = read_yaml(version_dir / "version.yaml")
        version["assumptions"] = [
            {
                "id": "A1",
                "name": f"{question_id} 测试假设",
                "statement": f"{question_id} 的测试假设陈述",
                "key": True,
            }
        ]
        write_yaml(version_dir / "version.yaml", version)

        manifest_path, manifest = question_manifest(problem_id, question_id)
        manifest.update(
            {
                "stage": "locally_completed",
                "status": "locally_completed",
                "accepted_assumption_version": 1,
                "accepted_formulation_version": 1,
                "conclusion": {
                    "conclusion_id": f"{question_id}_conclusion_v1",
                    "version": 1,
                    "content_hash": f"{question_id}-hash",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                "sanity": {"level_1_4": "PASS", "level_5": "PASS", "level_6": "PASS"},
                "optional_stages": {
                    "robustness": {"decision": "completed", "reason": f"{question_id} 鲁棒性测试结论"},
                    "ablation": {"decision": "completed", "reason": f"{question_id} 消融测试结论"},
                },
            }
        )
        write_yaml(manifest_path, manifest)
        ledger_rows.append(
            f"| 2026-01-01T00:00:00+00:00 | {question_id} | locally_completed | h | s | r | PASS | "
            f"{question_id} 的测试结论 | done |"
        )

    ledger_path.write_text("\n".join(ledger_rows) + "\n", encoding="utf-8")
    problem["cross_question_review"] = "passed"
    problem["cross_question_review_reason"] = "测试通过"
    write_json(problem_dir(problem_id) / "problem_state.json", problem)

    result = build_final_summary(problem_id)
    text = (project_root / result["summary"]).read_text(encoding="utf-8")

    assert "待填写" not in text
    for question_id in problem["questions"]:
        assert question_id in text
        assert f"{question_id} 的测试结论" in text
