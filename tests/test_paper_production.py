from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from manifest import sha256_file  # noqa: E402
from paper_content import freeze_content  # noqa: E402
from paper_production import produce_paper, select_template  # noqa: E402
from test_latex_qa import write_text_pdf  # noqa: E402


def valid_result(metric_hash: str) -> dict[str, object]:
    return {
        "question_id": "Q1",
        "model_id": "model-q1-v1",
        "assumptions": ["冻结证据所记录的假设成立。"],
        "baseline": {
            "model_id": "baseline-q1-v1",
            "metric": "score",
            "value": 0.60,
            "unit": "dimensionless",
        },
        "parameters": {"rate": {"value": 0.2, "unit": "1/day"}},
        "metrics": {
            "score": {
                "value": 0.75,
                "unit": "dimensionless",
                "source_path": "results/q1-metric.json",
                "source_hash": metric_hash,
                "finite": True,
            }
        },
        "units": {"score": "dimensionless"},
        "run_manifest": {"run_id": "run-q1-001", "status": "success", "seed": 1729},
        "validation_plan": {
            "validation_cycle_id": "validation-q1-001",
            "threshold": 0.70,
            "split": "holdout",
            "scope": "Q1 test observations",
            "seed": 1729,
            "method": "blocked holdout",
        },
        "validation_history": [],
        "validation_manifest": {
            "validation_cycle_id": "validation-q1-001",
            "status": "pass",
        },
        "figure_manifests": [],
        "claims": [
            {
                "claim_id": "claim-q1-01",
                "statement": "冻结结果的得分为 0.75。",
                "metric": "score",
                "source_path": "results/q1-metric.json",
                "source_hash": metric_hash,
            }
        ],
        "freeze_status": "confirmed",
    }


def valid_content(result_hash: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "language": "zh-CN",
        "requirement_manifests": [],
        "abstract": {
            "intro_sentences": [
                "该应用背景下存在需要解决的建模问题。",
                "本文完成了各问的建模、求解与验证。",
            ],
            "question_paragraphs": [
                {
                    "question_id": "Q1",
                    "leading_summary": "本问给出相应问题的求解目标。",
                    "modeling_steps": "根据冻结证据完成建模、求解与必要检验。",
                    "answer": "最终答案以已确认的结果合同为准。",
                }
            ],
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
            "5": {
                "title": "模型的建立与求解",
                "questions": [
                    {
                        "question_id": "Q1",
                        "title": "第一问",
                        "subsections": {
                            "5.1.1": {"title": "建模", "content": "依据冻结证据建模。"},
                            "5.1.2": {"title": "计算", "content": "依据冻结证据计算。"},
                        },
                    }
                ],
            },
            "6": {"title": "模型检验", "content": "按问引用已通过的检验证据。"},
            "7": {"title": "模型评价与推广/改进", "content": "说明局限与改进范围。"},
            "8": {"title": "结论", "content": "汇总冻结证据支持的结论。"},
        },
        "symbols": [{"symbol": "x", "description": "决策变量", "unit": "无量纲"}],
        "claims": [
            {
                "question_id": "Q1",
                "claim_id": "claim-q1-01",
                "statement": "冻结结果的得分为 0.75。",
                "source_path": "results/q1-result.json",
                "source_hash": result_hash,
                "important": True,
            }
        ],
        "figure_references": [],
        "table_references": [],
        "references": [],
        "code_appendix": [],
        "ai_use_disclosure": [],
        "human_review_records": [],
        "supplemental_appendix": [],
    }


class PaperProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fallback = self.root / "fallback"
        self.fallback.mkdir()
        (self.fallback / "main.tex").write_text(
            "\\documentclass{ctexart}\n"
            "\\begin{document}\n"
            "\\input{paper-frontmatter.tex}\n"
            "% BODY_START\n\\label{mm-body-start}\n"
            "\\input{paper-body.tex}\n"
            "\\label{mm-body-end}\n% BODY_END\n"
            "\\input{paper-appendices.tex}\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        self.user_template = self.root / "user-template"
        self.user_template.mkdir()
        (self.user_template / "main.tex").write_text("user template\n", encoding="utf-8")
        self.official = self.root / "official-template"
        self.official.mkdir()
        (self.official / "main.tex").write_text("official template\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_user_template_wins_and_is_hashed(self) -> None:
        report = select_template(
            user_template=self.user_template,
            fallback_dir=self.fallback,
            official_template=self.official,
        )
        self.assertEqual("user_provided", report["template_status"])
        self.assertEqual(str(self.user_template.resolve()), report["source"])
        self.assertRegex(report["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(report["submission_ready_eligible"])
        self.assertFalse((self.root / "paper/template").exists())

    def test_user_role_wins_when_user_and_official_paths_are_identical(self) -> None:
        (self.user_template / "template-manifest.json").write_text(
            json.dumps(
                {
                    "status": "verified",
                    "source_url": "https://contest.example/template.zip",
                    "license": "contest-use",
                    "verification_date": "2026-08-28",
                    "main_entry": "main.tex",
                    "engine": "xelatex",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = select_template(
            user_template=self.user_template,
            fallback_dir=self.fallback,
            official_template=self.user_template,
        )
        self.assertEqual("user_provided", report["template_status"])

    def test_missing_template_is_compilable_fallback_but_not_submission_ready(self) -> None:
        report = select_template(user_template=None, fallback_dir=self.fallback)
        self.assertEqual("fallback_non_submission", report["template_status"])
        self.assertFalse(report["submission_ready_eligible"])
        self.assertEqual("main.tex", report["main_entry"])

    def test_unverified_official_cannot_claim_verified_official_status(self) -> None:
        report = select_template(
            user_template=None,
            fallback_dir=self.fallback,
            official_template=self.official,
        )
        self.assertNotEqual("official_verified", report["template_status"])
        self.assertFalse(report["submission_ready_eligible"])

        (self.official / "template-manifest.json").write_text(
            json.dumps(
                {
                    "status": "verified",
                    "source_url": "https://contest.example/official-template.zip",
                    "license": "contest-use",
                    "verification_date": "2026-08-28",
                    "main_entry": "main.tex",
                    "engine": "xelatex",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        verified = select_template(
            user_template=None,
            fallback_dir=self.fallback,
            official_template=self.official,
        )
        self.assertEqual("official_verified", verified["template_status"])
        self.assertTrue(verified["submission_ready_eligible"])

    def test_template_tree_rejects_symlinks(self) -> None:
        target = self.root / "outside.tex"
        target.write_text("outside\n", encoding="utf-8")
        (self.user_template / "linked.tex").symlink_to(target)
        with self.assertRaises(ValueError):
            select_template(user_template=self.user_template, fallback_dir=self.fallback)

    def make_project(self, *, gate3: str = "confirmed", validation: str = "pass") -> tuple[Path, Path]:
        project = self.root / f"project-{gate3}-{validation}"
        iteration = project / "iterations/v001"
        for relative in (
            "state",
            "code",
            "data",
            "results",
            "figures",
            "paper",
            "manifests",
        ):
            (iteration / relative).mkdir(parents=True, exist_ok=True)
        (project / "qa").mkdir()
        current = {
            "schema_version": "2",
            "project_id": "fixture-project-1234",
            "active_iteration": "v001",
            "question_sources": {"Q1": "v001"},
            "gates": {"gate1": "confirmed", "gate2": "confirmed", "gate3": gate3},
            "status": "in_progress",
            "updated_at": "2026-08-28T00:00:00Z",
        }
        (project / "current.json").write_text(
            json.dumps(current, sort_keys=True) + "\n", encoding="utf-8"
        )
        handoff = {
            "state": {
                "validation_status": validation,
                "invalidated_stages": [],
            }
        }
        (iteration / "state/handoff.json").write_text(
            json.dumps(handoff, sort_keys=True) + "\n", encoding="utf-8"
        )

        metric = iteration / "results/q1-metric.json"
        metric.write_text('{"score": 0.75}\n', encoding="utf-8")
        result = iteration / "results/q1-result.json"
        result.write_text(
            json.dumps(valid_result(sha256_file(metric)), ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        frozen = iteration / "paper/frozen-content.json"
        freeze_content(
            valid_content(sha256_file(result)),
            output_path=frozen,
            evidence_root=iteration,
        )
        return project, frozen

    def make_compiler(
        self,
        *,
        exit_code: int = 0,
        write_pdf: bool = True,
        build_log: str | None = None,
        symlink_pdf: bool = False,
    ) -> Path:
        compiler = self.root / f"compiler-{exit_code}-{int(write_pdf)}"
        fixture_pdf = compiler.with_suffix(".pdf")
        fixture_aux = compiler.with_suffix(".aux")
        write_text_pdf(fixture_pdf, 26)
        fixture_aux.write_text(
            "\\newlabel{mm-body-start}{{1}{1}}\n"
            "\\newlabel{mm-body-end}{{8}{26}}\n",
            encoding="utf-8",
        )
        compiler.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "out = None\n"
            "for i, arg in enumerate(args):\n"
            "    if arg in ('--outdir', '-output-directory') and i + 1 < len(args): out = args[i + 1]\n"
            "    elif arg.startswith('-outdir='): out = arg.split('=', 1)[1]\n"
            "target = pathlib.Path(out or '.')\n"
            "target.mkdir(parents=True, exist_ok=True)\n"
            f"write_pdf = {write_pdf!r}\n"
            "if write_pdf:\n"
            "    source = pathlib.Path(__file__).with_suffix('.pdf')\n"
            f"    symlink_pdf = {symlink_pdf!r}\n"
            "    (target / 'main.pdf').symlink_to(source) if symlink_pdf else shutil.copyfile(source, target / 'main.pdf')\n"
            "    shutil.copyfile(pathlib.Path(__file__).with_suffix('.aux'), target / 'main.aux')\n"
            f"build_log = {build_log!r}\n"
            "if build_log is not None: (target / 'main.log').write_text(build_log)\n"
            "sys.stderr.write('controlled compiler stderr\\n')\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)
        return compiler

    def environment_manifest(
        self,
        project: Path,
        compiler: Path,
        *,
        tools: list[dict[str, object]] | None = None,
    ) -> Path:
        path = project / "qa/environment.json"
        payload = {
            "status": "warning",
            "project_root": str(project),
            "python": {"status": "pass", "path": sys.executable},
            "packages": [],
            "latex": {
                "status": "pass",
                "selected": "tectonic",
                "tools": tools or [
                    {
                        "name": "tectonic",
                        "status": "available",
                        "path": str(compiler),
                        "version": "fixture compiler 1",
                    }
                ],
                "message": "fixture",
            },
            "template": {"status": "fallback_non_submission"},
            "blockers": [],
            "warnings": ["fallback"],
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_unknown_gate_three_stops_before_template_copy_or_compiler(self) -> None:
        project, content = self.make_project(gate3="pending")
        compiler = self.make_compiler()
        invoked = self.root / "compiler-invoked"
        compiler.write_text(
            compiler.read_text(encoding="utf-8").replace(
                "args = sys.argv[1:]",
                f"pathlib.Path({str(invoked)!r}).write_text('yes')\nargs = sys.argv[1:]",
            ),
            encoding="utf-8",
        )
        environment = self.environment_manifest(project, compiler)

        with self.assertRaises(ValueError):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=None,
                compiler=compiler,
            )

        self.assertFalse(invoked.exists())
        self.assertFalse((project / "iterations/v001/paper/template").exists())
        self.assertFalse((project / "iterations/v001/paper/paper_manifest.json").exists())

    def test_stale_frozen_evidence_stops_before_compilation(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        result = project / "iterations/v001/results/q1-result.json"
        result.write_text(result.read_text(encoding="utf-8") + " ", encoding="utf-8")

        with self.assertRaises(ValueError):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=None,
                compiler=compiler,
            )

        self.assertFalse((project / "iterations/v001/paper/template").exists())

    def test_frozen_wrapper_cannot_omit_declared_content_evidence(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        payload = json.loads(content.read_text(encoding="utf-8"))
        payload["evidence"] = []
        content.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=None,
                compiler=compiler,
            )

        self.assertFalse((project / "iterations/v001/paper/template").exists())

    def test_compiler_failure_keeps_log_and_failure_manifest(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(exit_code=9, write_pdf=False)
        environment = self.environment_manifest(project, compiler)

        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=compiler,
        )

        self.assertEqual("fail", report["status"])
        self.assertEqual(9, report["compiler"]["attempts"][0]["exit_code"])
        self.assertEqual(
            sha256_file(compiler),
            report["compiler"]["attempts"][0]["compiler_sha256"],
        )
        log = project / report["compiler"]["attempts"][0]["log_path"]
        self.assertTrue(log.is_file())
        self.assertIn("controlled compiler stderr", log.read_text(encoding="utf-8"))
        manifest = project / "iterations/v001/paper/paper_manifest.json"
        self.assertTrue(manifest.is_file())
        self.assertFalse((project / "iterations/v001/paper/paper.pdf").exists())

    def test_zero_exit_without_pdf_is_audited_failure(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(exit_code=0, write_pdf=False)
        environment = self.environment_manifest(project, compiler)
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=self.fallback,
            compiler=compiler,
        )
        self.assertEqual("fail", report["status"])
        self.assertIn("PDF", " ".join(report["failed_checks"]))

    def test_symlinked_compiler_pdf_is_rejected_with_failure_manifest(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(symlink_pdf=True)
        environment = self.environment_manifest(project, compiler)

        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=compiler,
        )

        self.assertEqual("fail", report["status"])
        self.assertIn("symlink", " ".join(report["failed_checks"]).lower())
        self.assertTrue(
            (project / "iterations/v001/paper/paper_manifest.json").is_file()
        )

    def test_unresolved_reference_in_compiler_build_log_fails_pdf_qa(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(
            build_log="LaTeX Warning: There were undefined references.\n"
        )
        environment = self.environment_manifest(project, compiler)
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=compiler,
        )

        self.assertEqual("fail", report["status"])
        self.assertIn("reference", " ".join(report["failed_checks"]).lower())
        self.assertTrue(
            any(log["path"].endswith("main.log") for log in report["page_qa"]["logs"])
        )

    def test_successful_fallback_compile_has_authoritative_pdf_but_not_submission_ready(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=compiler,
        )

        self.assertEqual("pass", report["status"])
        self.assertEqual("fallback_non_submission", report["template_status"])
        self.assertEqual("fallback_non_submission", report["template"]["template_status"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual("pass", report["page_qa"]["status"])
        self.assertEqual("pass", report["page_qa"]["visual_qa"]["status"])
        pdf = project / report["pdf"]["path"]
        self.assertTrue(pdf.is_file())
        self.assertEqual(sha256_file(pdf), report["pdf"]["sha256"])

    def test_all_diagnosed_compilers_follow_priority_until_one_succeeds(self) -> None:
        project, content = self.make_project()
        latexmk = self.make_compiler(exit_code=9, write_pdf=False)
        xelatex = self.make_compiler(exit_code=0, write_pdf=True)
        environment = self.environment_manifest(
            project,
            latexmk,
            tools=[
                {
                    "name": "latexmk",
                    "status": "available",
                    "path": str(latexmk),
                    "version": "fixture latexmk",
                },
                {
                    "name": "xelatex",
                    "status": "available",
                    "path": str(xelatex),
                    "version": "fixture xelatex",
                },
            ],
        )

        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=None,
        )

        self.assertEqual("pass", report["status"])
        self.assertEqual(
            ["latexmk", "xelatex"],
            [attempt["tool"] for attempt in report["compiler"]["attempts"]],
        )

    def test_existing_iteration_paper_output_is_never_overwritten(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        template_target = project / "iterations/v001/paper/template"
        template_target.mkdir()
        sentinel = template_target / "keep.txt"
        sentinel.write_text("old evidence\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=self.fallback,
                compiler=compiler,
            )
        self.assertEqual("old evidence\n", sentinel.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
