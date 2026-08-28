from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMA = (
    ROOT
    / "skills/math-modeling-paper-production/references/paper-content.schema.json"
)
sys.path.insert(0, str(SCRIPTS))

from manifest import sha256_file  # noqa: E402
from paper_content import (  # noqa: E402
    freeze_content,
    question_ids,
    referenced_figures,
    referenced_tables,
    validate_paper_content,
)


def valid_result(question_id: str, metric_hash: str) -> dict[str, object]:
    suffix = question_id.lower()
    claim_id = f"claim-{suffix}-01"
    return {
        "question_id": question_id,
        "model_id": f"model-{suffix}-v1",
        "assumptions": ["冻结证据所记录的假设成立。"],
        "baseline": {
            "model_id": f"baseline-{suffix}-v1",
            "metric": "score",
            "value": 0.60,
            "unit": "dimensionless",
        },
        "parameters": {"rate": {"value": 0.2, "unit": "1/day"}},
        "metrics": {
            "score": {
                "value": 0.75,
                "unit": "dimensionless",
                "source_path": f"results/{suffix}-metric.json",
                "source_hash": metric_hash,
                "finite": True,
            }
        },
        "units": {"score": "dimensionless"},
        "run_manifest": {
            "run_id": f"run-{suffix}-001",
            "status": "success",
            "seed": 1729,
        },
        "validation_plan": {
            "validation_cycle_id": f"validation-{suffix}-001",
            "threshold": 0.70,
            "split": "holdout",
            "scope": f"{question_id} test observations",
            "seed": 1729,
            "method": "blocked holdout",
        },
        "validation_history": [],
        "validation_manifest": {
            "validation_cycle_id": f"validation-{suffix}-001",
            "status": "pass",
        },
        "figure_manifests": [],
        "claims": [
            {
                "claim_id": claim_id,
                "statement": "冻结结果的得分为 0.75。",
                "metric": "score",
                "source_path": f"results/{suffix}-metric.json",
                "source_hash": metric_hash,
            }
        ],
        "freeze_status": "confirmed",
    }


def valid_content(question_count: int) -> dict[str, object]:
    questions = []
    paragraphs = []
    claims = []
    for number in range(1, question_count + 1):
        question_id = f"Q{number}"
        questions.append(
            {
                "question_id": question_id,
                "title": f"第{number}问",
                "subsections": {
                    f"5.{number}.1": {
                        "title": "建模",
                        "content": "依据冻结证据说明模型建立过程。",
                    },
                    f"5.{number}.2": {
                        "title": "计算",
                        "content": "依据冻结证据说明计算过程。",
                    },
                },
            }
        )
        paragraphs.append(
            {
                "question_id": question_id,
                "leading_summary": "本问给出相应问题的求解目标。",
                "modeling_steps": "根据冻结证据完成建模、求解与必要检验。",
                "answer": "最终答案以已确认的结果合同为准。",
            }
        )
        claims.append(
            {
                "question_id": question_id,
                "claim_id": f"claim-q{number}-01",
                "statement": "冻结结果的得分为 0.75。",
                "source_path": f"results/q{number}-result.json",
                "source_hash": "a" * 64,
                "important": True,
            }
        )

    return {
        "schema_version": "1",
        "language": "zh-CN",
        "requirement_manifests": [],
        "abstract": {
            "intro_sentences": [
                "该应用背景下存在需要解决的建模问题。",
                "本文完成了各问的建模、求解与验证。",
            ],
            "question_paragraphs": paragraphs,
        },
        "keywords": ["数学建模", "证据追踪"],
        "sections": {
            "1": {
                "title": "问题背景与重述",
                "subsections": {
                    "1.1": {"title": "问题背景", "content": "说明问题背景。"},
                    "1.2": {"title": "问题重述", "content": "重述待解决问题。"},
                },
            },
            "2": {"title": "问题分析", "content": "分析各问之间的联系。"},
            "3": {"title": "模型假设", "content": "列出有证据支持的模型假设。"},
            "4": {"title": "符号说明", "content": "符号与单位见符号表。"},
            "5": {"title": "模型的建立与求解", "questions": questions},
            "6": {"title": "模型检验", "content": "按问引用已通过的检验证据。"},
            "7": {"title": "模型评价与推广/改进", "content": "说明局限与改进范围。"},
            "8": {"title": "结论", "content": "汇总冻结证据支持的结论。"},
        },
        "symbols": [
            {"symbol": "x", "description": "决策变量", "unit": "无量纲"}
        ],
        "claims": claims,
        "figure_references": [],
        "table_references": [],
        "references": [],
        "code_appendix": [],
        "ai_use_disclosure": [],
        "human_review_records": [],
        "supplemental_appendix": [],
    }


class PaperContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.evidence = Path(self.temporary.name).resolve()
        (self.evidence / "results").mkdir()
        (self.evidence / "manifests").mkdir()
        (self.evidence / "figures").mkdir()
        self.result_hashes: dict[str, str] = {}
        for number in (1, 2):
            metric = self.evidence / f"results/q{number}-metric.json"
            metric.write_text('{"score": 0.75}\n', encoding="utf-8")
            result = valid_result(f"Q{number}", sha256_file(metric))
            result_path = self.evidence / f"results/q{number}-result.json"
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.result_hashes[f"Q{number}"] = sha256_file(result_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def content_with_evidence(self, question_count: int = 1) -> dict[str, object]:
        content = valid_content(question_count)
        for claim in content["claims"]:
            claim["source_hash"] = self.result_hashes[claim["question_id"]]
        return content

    def test_valid_chinese_content_is_accepted_and_helpers_preserve_order(self) -> None:
        content = self.content_with_evidence(question_count=2)
        self.assertEqual(
            [], validate_paper_content(content, evidence_root=self.evidence)
        )
        self.assertEqual(["Q1", "Q2"], question_ids(content))
        self.assertEqual([], referenced_figures(content))
        self.assertEqual([], referenced_tables(content))

    def test_abstract_requires_exactly_two_intro_sentences(self) -> None:
        content = valid_content(question_count=1)
        content["abstract"]["intro_sentences"] = ["只写了一句。"]
        errors = validate_paper_content(content)
        self.assertTrue(any("intro_sentences" in error and "two" in error for error in errors))

    def test_stale_abstract_intro_sibling_is_rejected(self) -> None:
        content = valid_content(question_count=1)
        content["abstract"]["intro"] = "旧接口不应被接受。"
        errors = validate_paper_content(content)
        self.assertTrue(any("abstract.intro" in error and "unsupported" in error for error in errors))

    def test_abstract_requires_one_functional_paragraph_per_question(self) -> None:
        content = valid_content(question_count=2)
        content["abstract"]["question_paragraphs"] = [
            content["abstract"]["question_paragraphs"][0]
        ]
        errors = validate_paper_content(content)
        self.assertTrue(any("Q2" in error for error in errors))

        content = valid_content(question_count=2)
        content["abstract"]["question_paragraphs"][1] = copy.deepcopy(
            content["abstract"]["question_paragraphs"][0]
        )
        errors = validate_paper_content(content)
        self.assertTrue(any("Q1" in error and "exactly one" in error for error in errors))
        self.assertTrue(any("Q2" in error for error in errors))

        content = valid_content(question_count=1)
        del content["abstract"]["question_paragraphs"][0]["answer"]
        errors = validate_paper_content(content)
        self.assertTrue(any("answer" in error for error in errors))

    def test_symbol_table_has_exact_symbol_description_and_unit_columns(self) -> None:
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                content = valid_content(question_count=1)
                if mutation == "missing":
                    content["symbols"][0].pop("unit")
                else:
                    content["symbols"][0]["range"] = "all real values"
                errors = validate_paper_content(content)
                self.assertTrue(any("symbols[0]" in error for error in errors))

    def test_exact_top_level_titles_and_background_subsections_are_required(self) -> None:
        mutations = (
            ("1", "title", "问题重述"),
            ("6", "title", "模型的评价、改进与推广"),
            ("8", "title", "总结"),
        )
        for section, field, value in mutations:
            with self.subTest(section=section):
                content = valid_content(question_count=1)
                content["sections"][section][field] = value
                errors = validate_paper_content(content)
                self.assertTrue(any(f"sections.{section}.title" in error for error in errors))

        content = valid_content(question_count=1)
        del content["sections"]["1"]["subsections"]["1.1"]
        self.assertTrue(any("1.1" in error for error in validate_paper_content(content)))

    def test_each_question_requires_only_numbered_modeling_and_calculation_subsections(self) -> None:
        content = valid_content(question_count=2)
        del content["sections"]["5"]["questions"][1]["subsections"]["5.2.2"]
        errors = validate_paper_content(content)
        self.assertTrue(any("Q2" in error and "5.2.2" in error for error in errors))

        content = valid_content(question_count=1)
        content["sections"]["5"]["questions"][0]["subsections"]["5.1.3"] = {
            "title": "模型检验",
            "content": "不应放在此处。",
        }
        errors = validate_paper_content(content)
        self.assertTrue(any("5.1.3" in error and "unsupported" in error for error in errors))

    def test_claim_must_resolve_to_confirmed_result_contract_and_hash(self) -> None:
        content = self.content_with_evidence()
        content["claims"][0]["source_hash"] = "wrong"
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("hash" in error for error in errors))

        content = self.content_with_evidence()
        result_path = self.evidence / "results/q1-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["freeze_status"] = "draft"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        content["claims"][0]["source_hash"] = sha256_file(result_path)
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("confirmed" in error for error in errors))

        content = self.content_with_evidence()
        content["claims"][0]["source_path"] = "../escape.json"
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("safe relative path" in error for error in errors))

    def test_claim_id_and_question_must_match_frozen_result_contract(self) -> None:
        content = self.content_with_evidence()
        content["claims"][0]["claim_id"] = "claim-q1-unknown"
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("claim_id" in error and "result" in error for error in errors))

        content = self.content_with_evidence()
        content["claims"][0]["question_id"] = "Q2"
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("question_id" in error and "result" in error for error in errors))

    def test_paper_claim_statement_must_match_frozen_result_claim(self) -> None:
        content = self.content_with_evidence()
        content["claims"][0]["statement"] = "篡改后的结果得分为 0.99。"
        content["sections"]["8"]["content"] = "篡改后的结果得分为 0.99。"

        errors = validate_paper_content(content, evidence_root=self.evidence)

        self.assertTrue(
            any("statement" in error and "frozen result" in error for error in errors)
        )
        self.assertTrue(
            any("0.99" in error and "unsupported" in error for error in errors)
        )

    def test_claim_evidence_cannot_be_accepted_without_evidence_root(self) -> None:
        content = valid_content(question_count=1)

        errors = validate_paper_content(content)

        self.assertTrue(
            any("claims[0]" in error and "evidence_root" in error for error in errors)
        )

    def test_manifest_evidence_cannot_be_accepted_without_evidence_root(self) -> None:
        content = valid_content(question_count=1)
        content["figure_references"] = [
            {
                "figure_id": "plausible-but-fake",
                "manifest_path": "manifests/plausible-but-fake.json",
                "manifest_hash": "b" * 64,
            }
        ]

        errors = validate_paper_content(content)

        self.assertTrue(
            any(
                "figure_references[0]" in error and "evidence_root" in error
                for error in errors
            )
        )

    def test_unsupported_numbers_are_rejected_from_narrative(self) -> None:
        content = valid_content(question_count=1)
        content["sections"]["8"]["content"] = "未经证据支持，指标达到 99.9%。"
        errors = validate_paper_content(content)
        self.assertTrue(any("99.9%" in error and "unsupported" in error for error in errors))

    def test_bold_is_limited_to_abstract_or_registered_important_claims(self) -> None:
        content = valid_content(question_count=1)
        content["sections"]["2"]["content"] = r"任意使用 \textbf{加粗文字}。"
        errors = validate_paper_content(content)
        self.assertTrue(any("textbf" in error for error in errors))

        content = valid_content(question_count=1)
        content["abstract"]["intro_sentences"][0] = r"背景中存在 \textbf{建模问题}。"
        self.assertFalse(any("textbf" in error for error in validate_paper_content(content)))

    def test_figure_and_table_references_resolve_to_hashed_verified_manifests(self) -> None:
        source = self.evidence / "results/q1-figure-source.json"
        source.write_text('{"score": 0.75}\n', encoding="utf-8")
        pdf = self.evidence / "figures/q1.pdf"
        pdf.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Page/MediaBox[0 0 240.945 144]>>endobj\n%%EOF\n"
        )
        svg = self.evidence / "figures/q1.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="50mm"></svg>\n',
            encoding="utf-8",
        )
        figure_manifest = {
            "schema_version": "1",
            "figure_id": "q1-main",
            "role": "evidence",
            "question_id": "Q1",
            "claim_id": "claim-q1-01",
            "claim_type": "data",
            "exploratory_draft": False,
            "sources": [{"path": "results/q1-figure-source.json", "sha256": sha256_file(source)}],
            "outputs": [
                {"path": "figures/q1.pdf", "format": "pdf"},
                {"path": "figures/q1.svg", "format": "svg"},
            ],
            "axes": [
                {"id": "x", "label": "时间", "unit": "s"},
                {"id": "y", "label": "响应", "unit": "m"},
            ],
            "legend": {"present": False, "reason": "单序列"},
            "caption": "冻结结果的响应曲线。",
            "paper_reference": "图一",
            "paper_width_mm": 85,
            "grayscale_status": "pass",
            "colorblind_status": "pass",
            "render_status": "pass",
            "status": "verified",
        }
        figure_path = self.evidence / "manifests/q1-figure.json"
        figure_path.write_text(json.dumps(figure_manifest), encoding="utf-8")

        table_manifest = {
            "schema_version": "1",
            "table_id": "q1-summary",
            "question_id": "Q1",
            "sources": [{"path": "results/q1-figure-source.json", "sha256": sha256_file(source)}],
            "status": "verified",
        }
        table_path = self.evidence / "manifests/q1-table.json"
        table_path.write_text(json.dumps(table_manifest), encoding="utf-8")

        content = self.content_with_evidence()
        content["figure_references"] = [{
            "figure_id": "q1-main",
            "manifest_path": "manifests/q1-figure.json",
            "manifest_hash": sha256_file(figure_path),
        }]
        content["table_references"] = [{
            "table_id": "q1-summary",
            "manifest_path": "manifests/q1-table.json",
            "manifest_hash": sha256_file(table_path),
        }]
        self.assertEqual([], validate_paper_content(content, evidence_root=self.evidence))
        self.assertEqual(["q1-main"], referenced_figures(content))
        self.assertEqual(["q1-summary"], referenced_tables(content))

        figure_manifest["status"] = "draft"
        figure_path.write_text(json.dumps(figure_manifest), encoding="utf-8")
        content["figure_references"][0]["manifest_hash"] = sha256_file(figure_path)
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("figure" in error and "verified" in error for error in errors))

        figure_manifest["status"] = "verified"
        figure_path.write_text(json.dumps(figure_manifest), encoding="utf-8")
        content["figure_references"][0]["manifest_hash"] = sha256_file(figure_path)
        table_manifest["status"] = "draft"
        table_path.write_text(json.dumps(table_manifest), encoding="utf-8")
        content["table_references"][0]["manifest_hash"] = sha256_file(table_path)
        errors = validate_paper_content(content, evidence_root=self.evidence)
        self.assertTrue(any("table" in error and "verified" in error for error in errors))

    def test_english_abstract_requires_a_verified_requirement_manifest(self) -> None:
        content = valid_content(question_count=1)
        content["english_abstract"] = {
            "text": "Evidence-backed English abstract.",
            "keywords": ["modeling"],
        }
        errors = validate_paper_content(content)
        self.assertTrue(any("English" in error and "manifest" in error for error in errors))

        requirement = {
            "manifest_type": "template",
            "status": "verified",
            "required_sections": ["english_abstract"],
        }
        requirement_path = self.evidence / "manifests/template.json"
        requirement_path.write_text(json.dumps(requirement), encoding="utf-8")
        content["requirement_manifests"] = [{
            "kind": "template",
            "path": "manifests/template.json",
            "sha256": sha256_file(requirement_path),
        }]
        self.assertFalse(
            any(
                "English" in error
                for error in validate_paper_content(content, evidence_root=self.evidence)
            )
        )

    def test_english_abstract_null_is_not_treated_as_absent(self) -> None:
        content = valid_content(question_count=1)
        content["english_abstract"] = None
        errors = validate_paper_content(content)
        self.assertTrue(any("english_abstract must be an object" in error for error in errors))

    def test_schema_encodes_strict_chinese_content_shape(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        required = set(schema["required"])
        for field in (
            "language", "abstract", "keywords", "sections", "symbols", "claims",
            "figure_references", "table_references", "references", "code_appendix",
            "ai_use_disclosure", "human_review_records",
        ):
            self.assertIn(field, required)
        self.assertEqual("zh-CN", schema["properties"]["language"]["const"])
        intro = schema["properties"]["abstract"]["properties"]["intro_sentences"]
        self.assertEqual(2, intro["minItems"])
        self.assertEqual(2, intro["maxItems"])
        self.assertEqual(
            [str(number) for number in range(1, 9)],
            schema["properties"]["sections"]["required"],
        )
        symbol = schema["properties"]["symbols"]["items"]
        self.assertEqual(["symbol", "description", "unit"], symbol["required"])
        self.assertFalse(symbol["additionalProperties"])
        claim_required = schema["properties"]["claims"]["items"]["required"]
        self.assertIn("source_path", claim_required)
        self.assertIn("source_hash", claim_required)

    def test_freeze_is_deterministic_and_writes_only_after_validation(self) -> None:
        content = self.content_with_evidence()
        first = self.evidence / "paper-content-1.json"
        second = self.evidence / "paper-content-2.json"
        frozen = freeze_content(
            content,
            output_path=first,
            evidence_root=self.evidence,
        )
        freeze_content(content, output_path=second, evidence_root=self.evidence)
        self.assertEqual("complete", frozen["status"])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(
            [{
                "path": "results/q1-result.json",
                "sha256": self.result_hashes["Q1"],
            }],
            frozen["evidence"],
        )

        invalid = copy.deepcopy(content)
        invalid["sections"]["8"]["title"] = "总结"
        blocked = self.evidence / "blocked.json"
        blocked.write_bytes(b"preserve existing frozen evidence\n")
        with self.assertRaisesRegex(ValueError, "paper content validation failed"):
            freeze_content(invalid, output_path=blocked, evidence_root=self.evidence)
        self.assertEqual(b"preserve existing frozen evidence\n", blocked.read_bytes())

    def test_valid_freeze_refuses_to_overwrite_existing_snapshot(self) -> None:
        content = self.content_with_evidence()
        target = self.evidence / "paper-content.json"
        freeze_content(content, output_path=target, evidence_root=self.evidence)
        first_snapshot = target.read_bytes()
        changed = copy.deepcopy(content)
        changed["sections"]["2"]["content"] = "另一份仍然有效的分析叙述。"

        with self.assertRaises(FileExistsError):
            freeze_content(changed, output_path=target, evidence_root=self.evidence)

        self.assertEqual(first_snapshot, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
