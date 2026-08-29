from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from manifest import sha256_file  # noqa: E402
from paper_content import freeze_content  # noqa: E402
from paper_production import (  # noqa: E402
    _copy_selected_template,
    _write_new_bytes,
    produce_paper,
    recover_paper_publication,
    render_paper_pages,
    select_template,
)
import paper_production  # noqa: E402
from test_latex_qa import write_text_pdf  # noqa: E402


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def write_render_png(path: Path, *, width: int = 3, height: int = 2, blank: bool = False) -> None:
    rows = []
    for y in range(height):
        pixels = bytearray()
        for x in range(width):
            value = 255 if blank else 20 + ((x + y) % 2) * 180
            pixels.extend((value, value, value))
        rows.append(b"\x00" + bytes(pixels))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + _png_chunk(b"IEND", b"")
    )


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
        self.project_index = 0
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
        self.local_official = self.root / "local-official-template"
        self.local_official.mkdir()
        (self.local_official / "main.tex").write_text(
            "local official template\n", encoding="utf-8"
        )

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

    def test_fallback_identity_cannot_be_laundered_through_user_slot(self) -> None:
        copied = self.root / "copied-fallback"
        shutil.copytree(self.fallback, copied)
        copied_main = self.root / "copied-fallback-main.tex"
        shutil.copyfile(self.fallback / "main.tex", copied_main)
        for candidate in (
            self.fallback,
            copied,
            self.fallback / "main.tex",
            copied_main,
        ):
            with self.subTest(candidate=candidate):
                report = select_template(
                    user_template=candidate,
                    fallback_dir=self.fallback,
                )
                self.assertEqual("fallback_non_submission", report["template_status"])
                self.assertFalse(report["submission_ready_eligible"])

    def write_verified_metadata(self, template: Path, *, valid: bool = True) -> None:
        (template / "template-manifest.json").write_text(
            json.dumps(
                {
                    "status": "verified" if valid else "unverified",
                    "source_url": "https://contest.example/template.zip",
                    "license": "contest-use",
                    "verification_date": "2026-08-28",
                    "sha256": "d" * 64,
                    "main_entry": "main.tex",
                    "engine": "xelatex",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_four_template_tiers_have_fixed_priority_and_unverified_falls_through(self) -> None:
        self.write_verified_metadata(self.official)
        self.write_verified_metadata(self.local_official)
        all_candidates = select_template(
            self.user_template,
            self.fallback,
            self.official,
            locally_verified_template=self.local_official,
        )
        self.assertEqual(str(self.user_template), all_candidates["source"])
        self.assertEqual("user", all_candidates["selection_tier"])

        explicit = select_template(
            None,
            self.fallback,
            self.official,
            locally_verified_template=self.local_official,
        )
        self.assertEqual(str(self.official), explicit["source"])
        self.assertEqual("explicit_official", explicit["selection_tier"])
        self.assertTrue(explicit["submission_ready_eligible"])

        self.write_verified_metadata(self.official, valid=False)
        local = select_template(
            None,
            self.fallback,
            self.official,
            locally_verified_template=self.local_official,
        )
        self.assertEqual(str(self.local_official), local["source"])
        self.assertEqual("locally_verified_official", local["selection_tier"])

        self.write_verified_metadata(self.local_official, valid=False)
        fallback = select_template(
            None,
            self.fallback,
            self.official,
            locally_verified_template=self.local_official,
        )
        self.assertEqual("fallback_non_submission", fallback["template_status"])
        self.assertEqual(str(self.fallback), fallback["source"])

        copied_fallback = self.root / "official-fallback-copy"
        shutil.copytree(self.fallback, copied_fallback)
        self.write_verified_metadata(self.local_official)
        local_after_fallback_official = select_template(
            None,
            self.fallback,
            copied_fallback,
            locally_verified_template=self.local_official,
        )
        self.assertEqual(
            "locally_verified_official",
            local_after_fallback_official["selection_tier"],
        )

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
                    "sha256": "d" * 64,
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

    def make_project(
        self,
        *,
        gate3: str = "confirmed",
        validation: str = "pass",
        english: bool = False,
    ) -> tuple[Path, Path]:
        self.project_index += 1
        project = self.root / f"project-{self.project_index}-{gate3}-{validation}"
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
            },
            "artifacts": [],
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
        paper_content = valid_content(sha256_file(result))
        if english:
            requirement = iteration / "manifests/english-template.json"
            requirement.write_text(
                json.dumps(
                    {
                        "manifest_type": "template",
                        "status": "verified",
                        "required_sections": ["english_abstract"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            paper_content["requirement_manifests"] = [
                {
                    "kind": "template",
                    "path": "manifests/english-template.json",
                    "sha256": sha256_file(requirement),
                }
            ]
            paper_content["english_abstract"] = {
                "text": "This exact authorized English abstract must survive assembly.",
                "keywords": ["modeling", "evidence"],
            }
        frozen = iteration / "paper/frozen-content.json"
        freeze_content(
            paper_content,
            output_path=frozen,
            evidence_root=iteration,
        )
        return project, frozen

    def custom_template(self, main: str) -> Path:
        template = self.root / f"custom-{len(list(self.root.glob('custom-*')))}"
        template.mkdir()
        (template / "main.tex").write_text(main, encoding="utf-8")
        return template

    def test_custom_template_requires_exact_ordered_generated_input_slots(self) -> None:
        valid = (
            "\\documentclass{ctexart}\n\\begin{document}\n"
            "% \\input{paper-body.tex} ignored comment\n"
            "\\input{paper-frontmatter.tex}\n"
            "\\clearpage\\input{paper-body.tex}\n"
            "\\input{paper-appendices.tex}\n\\end{document}\n"
        )
        invalid = (
            valid.replace("\\input{paper-body.tex}\n", "", 1),
            valid.replace(
                "\\input{paper-appendices.tex}",
                "\\input{paper-body.tex}\n\\input{paper-appendices.tex}",
            ),
            valid.replace(
                "\\input{paper-frontmatter.tex}\n\\clearpage\\input{paper-body.tex}",
                "\\input{paper-body.tex}\n\\input{paper-frontmatter.tex}",
            ),
        )
        for main in invalid:
            project, content = self.make_project()
            compiler = self.make_compiler()
            environment = self.environment_manifest(project, compiler)
            invoked = self.root / f"invoked-{project.name}"
            compiler.write_text(
                compiler.read_text(encoding="utf-8").replace(
                    "args = sys.argv[1:]",
                    f"pathlib.Path({str(invoked)!r}).write_text('yes')\nargs = sys.argv[1:]",
                ),
                encoding="utf-8",
            )
            with self.subTest(main=main):
                with self.assertRaises(ValueError):
                    produce_paper(
                        project,
                        "v001",
                        content,
                        environment,
                        template_path=self.custom_template(main),
                        compiler=compiler,
                    )
                self.assertFalse(invoked.exists())

    def test_generated_body_owns_markers_at_section_one_and_after_section_eight(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        template = self.custom_template(
            "\\documentclass{ctexart}\n\\begin{document}\n"
            "\\input{paper-frontmatter.tex}\n\\clearpage\n"
            "\\input{paper-body.tex}\n\\input{paper-appendices.tex}\n"
            "\\end{document}\n"
        )
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=template,
            compiler=compiler,
        )
        body_path = project / "iterations/v001/paper/template/paper-body.tex"
        body = body_path.read_text(encoding="utf-8")
        self.assertGreater(body.index("\\label{mm-body-start}"), body.index("\\section{问题背景与重述}"))
        self.assertGreater(body.index("\\label{mm-body-end}"), body.index("汇总冻结证据支持的结论。"))
        self.assertEqual("pass", report["status"])

    def test_body_start_marker_follows_a_section_one_page_transition(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(section_one_starts_new_page=True)
        environment = self.environment_manifest(project, compiler)
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=None,
            compiler=compiler,
        )
        self.assertEqual(2, report["page_qa"]["body_range"]["start"])

    def test_authorized_english_abstract_is_preserved_in_generated_frontmatter(self) -> None:
        project, content = self.make_project(english=True)
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
        frontmatter = (
            project / "iterations/v001/paper/template/paper-frontmatter.tex"
        ).read_text(encoding="utf-8")
        self.assertIn("This exact authorized English abstract must survive assembly.", frontmatter)
        self.assertIn("modeling, evidence", frontmatter)
        self.assertEqual("pass", report["status"])

    def make_compiler(
        self,
        *,
        exit_code: int = 0,
        write_pdf: bool = True,
        build_log: str | None = None,
        symlink_pdf: bool = False,
        mutate_template: bool = False,
        aux_tokens: list[str] | None = None,
        build_logs: list[str] | None = None,
        section_one_starts_new_page: bool = False,
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
            "counter_path = target / '.fixture-pass-count'\n"
            "pass_number = int(counter_path.read_text()) + 1 if counter_path.exists() else 1\n"
            "counter_path.write_text(str(pass_number))\n"
            f"mutate_template = {mutate_template!r}\n"
            "if mutate_template: (pathlib.Path.cwd() / 'main.tex').write_text('tampered during compile')\n"
            f"write_pdf = {write_pdf!r}\n"
            "if write_pdf:\n"
            "    source = pathlib.Path(__file__).with_suffix('.pdf')\n"
            f"    symlink_pdf = {symlink_pdf!r}\n"
            "    (target / 'main.pdf').symlink_to(source) if symlink_pdf else shutil.copyfile(source, target / 'main.pdf')\n"
            f"    aux_tokens = {aux_tokens!r}\n"
            f"    section_one_starts_new_page = {section_one_starts_new_page!r}\n"
            "    if section_one_starts_new_page:\n"
            "        body = (pathlib.Path.cwd() / 'paper-body.tex').read_text()\n"
            "        start_page = 2 if body.index('\\\\section{') < body.index('mm-body-start') else 1\n"
            "        (target / 'main.aux').write_text('\\\\newlabel{mm-body-start}{{1}{' + str(start_page) + '}}\\n\\\\newlabel{mm-body-end}{{8}{26}}\\n')\n"
            "    elif aux_tokens is None: shutil.copyfile(pathlib.Path(__file__).with_suffix('.aux'), target / 'main.aux')\n"
            "    else:\n"
            "        token = aux_tokens[min(pass_number - 1, len(aux_tokens) - 1)]\n"
            "        (target / 'main.aux').write_text('\\\\newlabel{mm-body-start}{{1}{1}}\\n\\\\newlabel{mm-body-end}{{8}{26}}\\n% ' + token + '\\n')\n"
            f"build_log = {build_log!r}\n"
            f"build_logs = {build_logs!r}\n"
            "if build_logs is not None: build_log = build_logs[min(pass_number - 1, len(build_logs) - 1)]\n"
            "if build_log is not None: (target / 'main.log').write_text(build_log)\n"
            "sys.stderr.write('controlled compiler stderr\\n')\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)
        return compiler

    def make_renderer(
        self,
        *,
        exit_code: int = 0,
        write_pages: bool = True,
        fail_once: bool = False,
        label: str | None = None,
    ) -> Path:
        directory = self.root / (label or f"renderer-{len(list(self.root.glob('renderer-*')))}")
        directory.mkdir()
        renderer = directory / "pdftoppm"
        source = directory / "renderer-page.png"
        write_render_png(source)
        renderer.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "if args == ['-v']:\n"
            "    version_counter = pathlib.Path(__file__).with_name('version-count.txt')\n"
            "    version_count = int(version_counter.read_text()) + 1 if version_counter.exists() else 1\n"
            "    version_counter.write_text(str(version_count))\n"
            "    print('pdftoppm version 99.0.0', file=sys.stderr)\n"
            "    raise SystemExit(0)\n"
            "pdf = pathlib.Path(args[3])\n"
            "out = pathlib.Path(args[4]).parent\n"
            "(out / 'renderer-args.txt').write_text(' '.join(args) + '\\n')\n"
            "counter = pathlib.Path(__file__).with_name('render-count.txt')\n"
            "render_count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
            "counter.write_text(str(render_count))\n"
            f"fail_once = {fail_once!r}\n"
            "fail_this_attempt = fail_once and render_count == 1\n"
            f"write_pages = {write_pages!r}\n"
            "if write_pages and not fail_this_attempt:\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    source = pathlib.Path(__file__).with_name('renderer-page.png')\n"
            "    for page in range(1, 27): shutil.copyfile(source, out / f'page-{page:03d}.png')\n"
            f"raise SystemExit(7 if fail_this_attempt else {exit_code})\n",
            encoding="utf-8",
        )
        renderer.chmod(renderer.stat().st_mode | stat.S_IXUSR)
        return renderer

    def renderer_evidence(self, renderer: Path) -> dict[str, object]:
        output = "pdftoppm version 99.0.0\n"
        return {
            "name": "pdftoppm",
            "status": "available",
            "path": str(renderer),
            "sha256": sha256_file(renderer),
            "version_command": [str(renderer), "-v"],
            "version_exit_code": 0,
            "version_signature": "pdftoppm version 99.0.0",
            "version_output": output,
            "version_output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "trust_basis": "user_supplied_preflight_binary",
        }

    def environment_manifest(
        self,
        project: Path,
        compiler: Path,
        *,
        tools: list[dict[str, object]] | None = None,
        renderer: Path | None = None,
        renderer_record: dict[str, object] | None = None,
        register: bool = True,
        registered_hash: str | None = None,
    ) -> Path:
        path = project / "qa/environment.json"
        payload = {
            "status": "warning",
            "project_root": str(project),
            "python": {"status": "pass", "path": sys.executable},
            "packages": [],
            "latex": {
                "status": "pass",
                "selected": "xelatex",
                "tools": tools or [
                    {
                        "name": "xelatex",
                        "status": "available",
                        "path": str(compiler),
                        "sha256": sha256_file(compiler),
                        "version": "fixture compiler 1",
                    }
                ],
                "message": "fixture",
            },
            "pdf_renderer": renderer_record
            or (
                self.renderer_evidence(renderer)
                if renderer is not None
                else {
                    "name": "pdftoppm",
                    "status": "not_supplied",
                    "path": None,
                    "sha256": None,
                    "version_command": None,
                    "version_exit_code": None,
                    "version_signature": None,
                    "version_output": None,
                    "version_output_sha256": None,
                    "trust_basis": "user_supplied_preflight_binary",
                }
            ),
            "template": {"status": "fallback_non_submission"},
            "blockers": [],
            "warnings": ["fallback"],
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        if register:
            iteration = project / "iterations/v001"
            handoff_path = iteration / "state/handoff.json"
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff["artifacts"] = [
                {
                    "path": path.relative_to(project).as_posix(),
                    "kind": "environment",
                    "description": "current preflight environment evidence",
                    "sha256": registered_hash or sha256_file(path),
                }
            ]
            handoff_path.write_text(
                json.dumps(handoff, sort_keys=True) + "\n", encoding="utf-8"
            )
        return path

    def test_unregistered_or_hash_mismatched_environment_stops_before_output(self) -> None:
        for mode in ("unregistered", "hash_mismatch"):
            project, content = self.make_project()
            compiler = self.make_compiler()
            environment = self.environment_manifest(
                project,
                compiler,
                register=mode != "unregistered",
                registered_hash="0" * 64 if mode == "hash_mismatch" else None,
            )
            with self.subTest(mode=mode):
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

    def test_compiler_replacement_after_preflight_stops_before_output(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        compiler.write_text(
            compiler.read_text(encoding="utf-8") + "\n# replaced after diagnosis\n",
            encoding="utf-8",
        )
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

    def test_nested_symlink_copy_race_never_writes_outside_destination(self) -> None:
        template = self.root / "nested-template"
        (template / "nested").mkdir(parents=True)
        (template / "nested/payload.tex").write_text("safe source\n", encoding="utf-8")
        (template / "main.tex").write_text(
            "\\input{paper-frontmatter.tex}\\input{paper-body.tex}"
            "\\input{paper-appendices.tex}",
            encoding="utf-8",
        )
        selection = select_template(template, self.fallback)
        destination = self.root / "copy-target"
        outside = self.root / "outside-copy"
        outside.mkdir()
        escaped = outside / "payload.tex"
        escaped.write_text("preserve me\n", encoding="utf-8")
        real_mkdir = os.mkdir

        def racing_mkdir(path: object, *args: object, **kwargs: object) -> None:
            if path == "nested" and kwargs.get("dir_fd") is not None:
                os.symlink(
                    outside,
                    "nested",
                    target_is_directory=True,
                    dir_fd=kwargs["dir_fd"],
                )
                return
            real_mkdir(path, *args, **kwargs)

        with patch("paper_production.os.mkdir", side_effect=racing_mkdir):
            with self.assertRaises(ValueError):
                _copy_selected_template(selection, destination)
        self.assertEqual("preserve me\n", escaped.read_text(encoding="utf-8"))

    def test_intermediate_parent_replacement_cannot_redirect_leaf_publication(self) -> None:
        destination_root = self.root / "publication-root"
        destination_parent = destination_root / "nested"
        outside = self.root / "outside-publication"
        displaced = self.root / "displaced-parent"
        destination_parent.mkdir(parents=True)
        outside.mkdir()
        target = destination_parent / "artifact.bin"
        real_open = os.open

        def racing_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if Path(path) == target and not destination_parent.is_symlink():
                destination_parent.rename(displaced)
                destination_parent.symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)

        with patch("paper_production.os.open", side_effect=racing_open):
            try:
                _write_new_bytes(target, b"audited payload", "race probe")
            except (OSError, ValueError):
                pass
        self.assertFalse((outside / "artifact.bin").exists())

    def test_final_pdf_collision_is_preserved_without_replacement(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        target = project / "iterations/v001/paper/paper.pdf"
        from paper_production import _write_new_bytes

        def racing_publish(destination: Path, data: bytes, label: str) -> None:
            if destination == target and not target.exists():
                target.write_text("concurrent owner\n", encoding="utf-8")
            _write_new_bytes(destination, data, label)

        with patch("paper_production._write_new_bytes", side_effect=racing_publish):
            with self.assertRaises(FileExistsError):
                produce_paper(
                    project,
                    "v001",
                    content,
                    environment,
                    template_path=None,
                    compiler=compiler,
                )
        self.assertEqual("concurrent owner\n", target.read_text(encoding="utf-8"))

    def test_template_mutation_during_compile_fails_audit_and_no_final_pdf(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(mutate_template=True)
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
        self.assertIn("template", " ".join(report["failed_checks"]).lower())
        self.assertFalse((project / "iterations/v001/paper/paper.pdf").exists())

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
        self.assertEqual("needs_review", report["page_qa"]["visual_qa"]["status"])
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
                    "sha256": sha256_file(latexmk),
                    "version": "fixture latexmk",
                },
                {
                    "name": "xelatex",
                    "status": "available",
                    "path": str(xelatex),
                    "sha256": sha256_file(xelatex),
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

    def test_direct_xelatex_runs_until_aux_is_stable_and_keeps_each_pass(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(
            aux_tokens=["stable", "stable"],
            build_logs=[
                "LaTeX Warning: There were undefined references.\n",
                "references resolved\n",
            ],
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
        self.assertEqual("pass", report["status"])
        passes = report["compiler"]["attempts"][0]["passes"]
        self.assertEqual(2, len(passes))
        self.assertTrue(all(item["command"] for item in passes))
        self.assertTrue(all((project / item["log_path"]).is_file() for item in passes))

    def test_direct_xelatex_aux_nonconvergence_fails_closed(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler(aux_tokens=["one", "two", "three", "four"])
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
        self.assertIn("converg", " ".join(report["failed_checks"]).lower())
        self.assertEqual(3, len(report["compiler"]["attempts"][0]["passes"]))

    def test_template_engine_conflict_stops_before_template_copy(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        template = self.custom_template(
            "\\documentclass{article}\\begin{document}"
            "\\input{paper-frontmatter.tex}\\input{paper-body.tex}"
            "\\input{paper-appendices.tex}\\end{document}"
        )
        self.write_verified_metadata(template)
        metadata = json.loads((template / "template-manifest.json").read_text())
        metadata["engine"] = "tectonic"
        (template / "template-manifest.json").write_text(
            json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=template,
                compiler=compiler,
            )
        self.assertFalse((project / "iterations/v001/paper/template").exists())

    def prepare_visual_finalization(
        self,
        *,
        render: bool = True,
        register_renderer: bool = True,
        renderer_exit_code: int = 0,
        renderer_write_pages: bool = True,
        renderer_fail_once: bool = False,
    ) -> tuple[Path, Path, Path, Path, Path, Path, dict[str, object]]:
        project, content = self.make_project()
        compiler = self.make_compiler()
        renderer = self.make_renderer(
            exit_code=renderer_exit_code,
            write_pages=renderer_write_pages,
            fail_once=renderer_fail_once,
        )
        environment = self.environment_manifest(
            project,
            compiler,
            renderer=renderer if register_renderer else None,
        )
        template = self.custom_template(
            "\\documentclass{article}\\begin{document}"
            "\\input{paper-frontmatter.tex}\\input{paper-body.tex}"
            "\\input{paper-appendices.tex}\\end{document}"
        )
        report = produce_paper(
            project,
            "v001",
            content,
            environment,
            template_path=template,
            compiler=compiler,
        )
        paper = project / "iterations/v001/paper"
        request = paper / "visual_review_request.json"
        render_manifest = paper / "paper_render_manifest.json"
        if render:
            render_paper_pages(project, "v001", renderer=renderer)
        review = project / "qa/paper-visual-review.json"
        review_payload = {
            "schema_version": "1",
            "manifest_type": "paper_visual_review",
            "iteration": "v001",
            "status": "pass",
            "pdf_sha256": report["pdf"]["sha256"],
            "render_manifest_sha256": sha256_file(render_manifest) if render else "0" * 64,
            "page_coverage": {"start": 1, "end": 26, "pages": 26},
            "checklist": {
                "blank_pages": "pass",
                "cropping": "pass",
                "garbled_text": "pass",
                "overlap": "pass",
                "abnormal_font_or_hidden_padding": "pass",
            },
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-08-28T12:00:00Z",
        }
        if render:
            review.write_text(
                json.dumps(review_payload, sort_keys=True) + "\n", encoding="utf-8"
            )
        return project, compiler, renderer, request, render_manifest, review, report

    def prepare_unpublished_render_success(
        self,
    ) -> tuple[Path, Path, Path, Path, dict[str, object]]:
        project, _, renderer, _, render_manifest, _, _ = (
            self.prepare_visual_finalization(render=False)
        )
        original_write_new_json = paper_production._write_new_json
        unpublished_payload: dict[str, object] | None = None

        def fail_canonical_publish(path: Path, payload: object) -> None:
            nonlocal unpublished_payload
            if path == render_manifest:
                self.assertIsInstance(payload, dict)
                unpublished_payload = json.loads(json.dumps(payload))
                raise OSError("injected canonical render manifest publish failure")
            original_write_new_json(path, payload)

        with patch(
            "paper_production._write_new_json", side_effect=fail_canonical_publish
        ):
            with self.assertRaisesRegex(
                OSError, "injected canonical render manifest publish failure"
            ):
                render_paper_pages(project, "v001", renderer=renderer)
        attempt = project / "iterations/v001/paper/render-attempts/attempt-001"
        self.assertEqual(
            "pass",
            json.loads((attempt / "attempt.json").read_text(encoding="utf-8"))["status"],
        )
        self.assertFalse(render_manifest.exists())
        self.assertIsNotNone(unpublished_payload)
        assert unpublished_payload is not None
        return project, renderer, render_manifest, attempt, unpublished_payload

    def test_render_requires_exact_current_preflight_renderer_evidence(self) -> None:
        cases = ("unregistered", "replacement", "different_basename", "manifest_tamper")
        for case in cases:
            with self.subTest(case=case):
                project, _, renderer, _, _, _, _ = self.prepare_visual_finalization(
                    render=False,
                    register_renderer=case != "unregistered",
                )
                requested = renderer
                if case == "replacement":
                    renderer.write_text(
                        renderer.read_text(encoding="utf-8") + "\n# replacement\n",
                        encoding="utf-8",
                    )
                elif case == "different_basename":
                    requested = self.make_renderer(label=f"unregistered-{project.name}")
                elif case == "manifest_tamper":
                    environment = project / "qa/environment.json"
                    environment.write_text(
                        environment.read_text(encoding="utf-8") + " ",
                        encoding="utf-8",
                    )

                with self.assertRaises(ValueError):
                    render_paper_pages(project, "v001", renderer=requested)
                self.assertFalse(
                    (project / "iterations/v001/paper/paper_render_manifest.json").exists()
                )

    def test_finalization_revalidates_expected_command_version_and_environment(self) -> None:
        for case in ("command", "version", "environment"):
            with self.subTest(case=case):
                project, _, _, _, render_manifest, review, _ = (
                    self.prepare_visual_finalization()
                )
                if case in ("command", "version"):
                    render = json.loads(render_manifest.read_text(encoding="utf-8"))
                    if case == "command":
                        render["generator"]["command"] = ["/bin/false"]
                    else:
                        render["renderer"]["version_output"] = "pdftoppm version 0.0.0"
                    render_manifest.write_text(
                        json.dumps(render, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    review_payload = json.loads(review.read_text(encoding="utf-8"))
                    review_payload["render_manifest_sha256"] = sha256_file(render_manifest)
                    review.write_text(
                        json.dumps(review_payload, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                else:
                    environment = project / "qa/environment.json"
                    environment.write_text(
                        environment.read_text(encoding="utf-8") + " ",
                        encoding="utf-8",
                    )

                with self.assertRaises(ValueError):
                    paper_production.finalize_paper(project, "v001", review)
                self.assertFalse(
                    (project / "iterations/v001/paper/paper_finalization.json").exists()
                )

    def test_render_api_owns_canonical_manifest_and_exact_pdf_provenance(self) -> None:
        project, _, _, request, _, review, candidate = self.prepare_visual_finalization()
        paper = project / "iterations/v001/paper"
        synthetic = project / "qa/synthetic-render.json"
        synthetic.write_text("{}\n", encoding="utf-8")
        renderer = self.make_renderer()
        with self.assertRaises(FileExistsError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertTrue((paper / "paper_render_manifest.json").is_file())
        args_text = next(
            (paper / "render-attempts/attempt-001/pages").glob("renderer-args.txt")
        ).read_text()
        self.assertIn(str(paper / "paper.pdf"), args_text)
        self.assertIn("-r 200", args_text)
        self.assertTrue(request.is_file())
        self.assertFalse(candidate["submission_ready"])
        review_payload = json.loads(review.read_text(encoding="utf-8"))
        review_payload["render_manifest_path"] = synthetic.relative_to(project).as_posix()
        review.write_text(json.dumps(review_payload, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            paper_production.finalize_paper(project, "v001", review)

    def test_render_api_failure_stays_non_ready_without_canonical_manifest(self) -> None:
        project, _, renderer, _, _, _, candidate = self.prepare_visual_finalization(
            render=False,
            renderer_exit_code=7,
            renderer_write_pages=False,
        )
        paper = project / "iterations/v001/paper"
        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertFalse((paper / "paper_render_manifest.json").exists())
        self.assertTrue((paper / "render-attempts/attempt-001/render.log").is_file())
        self.assertFalse(candidate["submission_ready"])

    def test_failed_render_attempt_is_immutable_and_retry_uses_next_attempt(self) -> None:
        project, _, renderer, _, render_manifest, _, _ = self.prepare_visual_finalization(
            render=False,
            renderer_fail_once=True,
        )
        paper = project / "iterations/v001/paper"
        first = paper / "render-attempts/attempt-001"
        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertTrue((first / "render.log").is_file())
        self.assertEqual(
            "failed",
            json.loads((first / "attempt.json").read_text(encoding="utf-8"))["status"],
        )
        self.assertFalse(render_manifest.exists())
        first_bytes = {
            path.relative_to(first).as_posix(): path.read_bytes()
            for path in first.rglob("*")
            if path.is_file()
        }

        rendered = render_paper_pages(project, "v001", renderer=renderer)

        second = paper / "render-attempts/attempt-002"
        self.assertTrue((second / "render.log").is_file())
        self.assertEqual("attempt-002", rendered["attempt"]["id"])
        self.assertTrue(render_manifest.is_file())
        self.assertTrue(
            all(
                (project / page["path"]).parent == second / "pages"
                for page in rendered["pages"]
            )
        )
        self.assertEqual(
            first_bytes,
            {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            },
        )
        canonical_bytes = render_manifest.read_bytes()
        with self.assertRaises(FileExistsError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertEqual(canonical_bytes, render_manifest.read_bytes())

    def test_render_manifest_publication_failure_recovers_without_rerender(self) -> None:
        project, renderer, render_manifest, attempt, unpublished_payload = (
            self.prepare_unpublished_render_success()
        )
        paper = project / "iterations/v001/paper"
        self.assertEqual(
            "1", (renderer.parent / "render-count.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "1", (renderer.parent / "version-count.txt").read_text(encoding="utf-8")
        )
        immutable_paper_bytes = {
            path.relative_to(paper).as_posix(): path.read_bytes()
            for path in paper.rglob("*")
            if path.is_file()
        }

        recovered = render_paper_pages(project, "v001", renderer=renderer)

        self.assertEqual(unpublished_payload, recovered)
        self.assertEqual("attempt-001", recovered["attempt"]["id"])
        self.assertTrue(render_manifest.is_file())
        self.assertEqual(
            "1", (renderer.parent / "render-count.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "1", (renderer.parent / "version-count.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(
            immutable_paper_bytes,
            {
                path.relative_to(paper).as_posix(): path.read_bytes()
                for path in paper.rglob("*")
                if path.is_file() and path != render_manifest
            },
        )
        self.assertEqual(
            ["attempt-001"],
            sorted(path.name for path in (paper / "render-attempts").iterdir()),
        )

    def test_render_manifest_recovery_rejects_coherent_page_and_attempt_mutation(self) -> None:
        project, renderer, render_manifest, attempt, _ = (
            self.prepare_unpublished_render_success()
        )
        attempt_path = attempt / "attempt.json"
        record = json.loads(attempt_path.read_text(encoding="utf-8"))
        first_page = project / record["pages"][0]["path"]
        write_render_png(first_page, width=4)
        record["pages"][0]["sha256"] = sha256_file(first_page)
        record["pages"][0]["width_px"] = 4
        attempt_path.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertFalse(render_manifest.exists())
        self.assertEqual("1", (renderer.parent / "render-count.txt").read_text(encoding="utf-8"))
        self.assertEqual("1", (renderer.parent / "version-count.txt").read_text(encoding="utf-8"))

    def test_render_manifest_recovery_rejects_tampered_success_state(self) -> None:
        cases = (
            "attempt_hash",
            "timestamp",
            "log",
            "page",
            "extra_page",
            "page_order",
            "path",
            "renderer",
            "status",
            "noncanonical_bytes",
        )
        for case in cases:
            with self.subTest(case=case):
                project, renderer, render_manifest, attempt, _ = (
                    self.prepare_unpublished_render_success()
                )
                attempt_path = attempt / "attempt.json"
                record = json.loads(attempt_path.read_text(encoding="utf-8"))
                if case == "attempt_hash":
                    record["candidate"]["pdf_sha256"] = "0" * 64
                elif case == "timestamp":
                    record["created_at"] = "2026-08-28T23:59:59Z"
                elif case == "log":
                    (attempt / "render.log").write_text(
                        (attempt / "render.log").read_text(encoding="utf-8")
                        + "tampered\n",
                        encoding="utf-8",
                    )
                elif case == "page":
                    first_page = project / record["pages"][0]["path"]
                    write_render_png(first_page, width=4)
                elif case == "extra_page":
                    first_page = project / record["pages"][0]["path"]
                    shutil.copyfile(first_page, attempt / "pages/extra.png")
                elif case == "page_order":
                    first = record["pages"][0]
                    second = record["pages"][1]
                    for key in ("path", "sha256", "width_px", "height_px"):
                        first[key], second[key] = second[key], first[key]
                elif case == "path":
                    record["pages"][0]["path"] = record["candidate"][
                        "manifest_sha256"
                    ]
                elif case == "renderer":
                    record["renderer"]["version_signature"] = (
                        "pdftoppm version 0.0.0"
                    )
                elif case == "noncanonical_bytes":
                    attempt_path.write_bytes(attempt_path.read_bytes() + b" ")
                else:
                    record["status"] = "failed"
                    record["error"] = None
                if case not in (
                    "log",
                    "page",
                    "extra_page",
                    "noncanonical_bytes",
                ):
                    attempt_path.write_text(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                            allow_nan=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                with self.assertRaises(ValueError):
                    render_paper_pages(project, "v001", renderer=renderer)
                self.assertFalse(render_manifest.exists())
                self.assertEqual(
                    "1",
                    (renderer.parent / "render-count.txt").read_text(encoding="utf-8"),
                )

    def test_render_manifest_recovery_rejects_nonfinal_or_multiple_success(self) -> None:
        for mode in ("nonfinal", "multiple"):
            with self.subTest(mode=mode):
                project, renderer, render_manifest, first, _ = (
                    self.prepare_unpublished_render_success()
                )
                second = first.parent / "attempt-002"
                shutil.copytree(first, second)
                second_record_path = second / "attempt.json"
                second_record = json.loads(
                    second_record_path.read_text(encoding="utf-8")
                )
                second_record["attempt_id"] = "attempt-002"
                if mode == "nonfinal":
                    second_record["status"] = "failed"
                    second_record["error"] = "synthetic later failure"
                    second_record["pages"] = []
                second_record_path.write_text(
                    json.dumps(
                        second_record,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        allow_nan=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with self.assertRaises(ValueError):
                    render_paper_pages(project, "v001", renderer=renderer)
                self.assertFalse(render_manifest.exists())
                self.assertEqual(
                    "1",
                    (renderer.parent / "render-count.txt").read_text(encoding="utf-8"),
                )

    def test_render_manifest_recovery_rejects_tampered_prior_failure(self) -> None:
        project, _, renderer, _, render_manifest, _, _ = (
            self.prepare_visual_finalization(render=False, renderer_fail_once=True)
        )
        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        original_write_new_json = paper_production._write_new_json

        def fail_canonical_publish(path: Path, payload: object) -> None:
            if path == render_manifest:
                raise OSError("injected canonical render manifest publish failure")
            original_write_new_json(path, payload)

        with patch(
            "paper_production._write_new_json", side_effect=fail_canonical_publish
        ):
            with self.assertRaisesRegex(
                OSError, "injected canonical render manifest publish failure"
            ):
                render_paper_pages(project, "v001", renderer=renderer)

        first_record_path = (
            project
            / "iterations/v001/paper/render-attempts/attempt-001/attempt.json"
        )
        first_record = json.loads(first_record_path.read_text(encoding="utf-8"))
        first_record["candidate"]["manifest_sha256"] = "0" * 64
        first_record_path.write_text(
            json.dumps(
                first_record,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertFalse(render_manifest.exists())
        self.assertEqual(
            "2", (renderer.parent / "render-count.txt").read_text(encoding="utf-8")
        )

    def test_render_manifest_recovery_preserves_prior_failure_audit(self) -> None:
        project, _, renderer, _, render_manifest, _, _ = (
            self.prepare_visual_finalization(render=False, renderer_fail_once=True)
        )
        with self.assertRaises(ValueError):
            render_paper_pages(project, "v001", renderer=renderer)
        original_write_new_json = paper_production._write_new_json

        def fail_canonical_publish(path: Path, payload: object) -> None:
            if path == render_manifest:
                raise OSError("injected canonical render manifest publish failure")
            original_write_new_json(path, payload)

        with patch(
            "paper_production._write_new_json", side_effect=fail_canonical_publish
        ):
            with self.assertRaisesRegex(
                OSError, "injected canonical render manifest publish failure"
            ):
                render_paper_pages(project, "v001", renderer=renderer)
        attempts = project / "iterations/v001/paper/render-attempts"
        immutable_attempt_bytes = {
            path.relative_to(attempts).as_posix(): path.read_bytes()
            for path in attempts.rglob("*")
            if path.is_file()
        }

        recovered = render_paper_pages(project, "v001", renderer=renderer)

        self.assertEqual("attempt-002", recovered["attempt"]["id"])
        self.assertEqual(
            ["failed", "pass"],
            [
                json.loads(
                    (attempts / f"attempt-{number:03d}/attempt.json").read_text(
                        encoding="utf-8"
                    )
                )["status"]
                for number in (1, 2)
            ],
        )
        self.assertEqual(
            immutable_attempt_bytes,
            {
                path.relative_to(attempts).as_posix(): path.read_bytes()
                for path in attempts.rglob("*")
                if path.is_file()
            },
        )
        self.assertEqual(
            "2", (renderer.parent / "render-count.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(
            "2", (renderer.parent / "version-count.txt").read_text(encoding="utf-8")
        )

    def test_render_manifest_recovery_rejects_existing_divergent_manifest(self) -> None:
        project, _, renderer, _, render_manifest, _, _ = (
            self.prepare_visual_finalization()
        )
        divergent = json.loads(render_manifest.read_text(encoding="utf-8"))
        divergent["pdf_sha256"] = "0" * 64
        render_manifest.write_text(
            json.dumps(
                divergent,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        divergent_bytes = render_manifest.read_bytes()

        with self.assertRaises(FileExistsError):
            render_paper_pages(project, "v001", renderer=renderer)
        self.assertEqual(divergent_bytes, render_manifest.read_bytes())
        self.assertEqual(
            "1", (renderer.parent / "render-count.txt").read_text(encoding="utf-8")
        )

    def test_concurrent_render_attempt_directory_collision_fails_without_overwrite(self) -> None:
        project, _, renderer, _, render_manifest, _, _ = self.prepare_visual_finalization(
            render=False
        )
        paper = project / "iterations/v001/paper"
        original = paper_production._mkdir_new
        sentinel = paper / "render-attempts/attempt-001/concurrent.txt"

        def collide(path: Path, label: str) -> Path:
            if path.name == "attempt-001":
                path.mkdir()
                sentinel.write_text("concurrent owner\n", encoding="utf-8")
            return original(path, label)

        with patch("paper_production._mkdir_new", side_effect=collide):
            with self.assertRaises(FileExistsError):
                render_paper_pages(project, "v001", renderer=renderer)
        self.assertEqual("concurrent owner\n", sentinel.read_text(encoding="utf-8"))
        self.assertFalse(render_manifest.exists())

    def test_compile_render_review_finalize_is_immutable_and_does_not_recompile(self) -> None:
        project, compiler, _, request, render_manifest, review, candidate = (
            self.prepare_visual_finalization()
        )
        paper = project / "iterations/v001/paper"
        manifest = paper / "paper_manifest.json"
        before = {
            "manifest": sha256_file(manifest),
            "pdf": sha256_file(paper / "paper.pdf"),
            "passes": (paper / "build/attempt-01/.fixture-pass-count").read_text(),
        }
        self.assertFalse(candidate["submission_ready"])
        self.assertEqual(
            "iterations/v001/paper/paper_finalization.json",
            candidate["readiness"]["authority"],
        )
        self.assertTrue(request.is_file())

        final = paper_production.finalize_paper(project, "v001", review)

        self.assertTrue(final["submission_ready"])
        self.assertTrue(final["readiness_authority"])
        self.assertEqual(sha256_file(render_manifest), final["render_manifest"]["sha256"])
        self.assertEqual(before["manifest"], sha256_file(manifest))
        self.assertEqual(before["pdf"], sha256_file(paper / "paper.pdf"))
        self.assertEqual(
            before["passes"],
            (paper / "build/attempt-01/.fixture-pass-count").read_text(),
        )
        with self.assertRaises(FileExistsError):
            paper_production.finalize_paper(project, "v001", review)

    def test_finalization_record_has_shared_strict_validator(self) -> None:
        """Catches readiness callers trusting one boolean instead of Task 9 authority."""

        project, _, _, _, _, review, _ = self.prepare_visual_finalization()
        final = paper_production.finalize_paper(project, "v001", review)

        self.assertEqual(
            [], paper_production.validate_paper_finalization_record(final)
        )
        mutations: list[dict[str, object]] = []
        extra = json.loads(json.dumps(final))
        extra["agent_override"] = True
        mutations.append(extra)
        not_ready = json.loads(json.dumps(final))
        not_ready["submission_ready"] = False
        mutations.append(not_ready)
        stale_path = json.loads(json.dumps(final))
        stale_path["candidate_pdf"]["path"] = "paper.pdf"
        mutations.append(stale_path)
        incomplete_pages = json.loads(json.dumps(final))
        incomplete_pages["render_manifest"]["pages"].pop(0)
        mutations.append(incomplete_pages)
        failed_review = json.loads(json.dumps(final))
        failed_review["visual_review"]["checklist"]["cropping"] = "fail"
        mutations.append(failed_review)

        for payload in mutations:
            with self.subTest(payload=payload):
                self.assertTrue(
                    paper_production.validate_paper_finalization_record(payload)
                )

    def test_project_backed_finalization_authority_loads_every_bound_file(self) -> None:
        """Catches shape-valid finalization authorizing absent subordinate files."""

        validator = getattr(
            paper_production, "validate_paper_finalization_authority", None
        )
        self.assertTrue(
            callable(validator),
            "Task 9 must expose a project-backed finalization authority validator",
        )
        if not callable(validator):
            return

        project, _, _, _, _, review, _ = self.prepare_visual_finalization()
        final = paper_production.finalize_paper(project, "v001", review)
        authority = validator(project, "v001")
        self.assertEqual(final, authority["record"])
        self.assertEqual(
            "iterations/v001/paper/paper_finalization.json", authority["path"]
        )
        self.assertEqual(
            sha256_file(project / authority["path"]), authority["sha256"]
        )

        (project / final["candidate_manifest"]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "candidate manifest"):
            validator(project, "v001")

    def test_finalization_rejects_stale_or_incomplete_visual_evidence(self) -> None:
        cases = (
            "wrong_pdf",
            "missing_page",
            "duplicate_page",
            "arbitrary_bytes",
            "blank_png",
            "tampered_pdf",
            "tampered_request",
            "unknown_check",
            "stale_project",
        )
        for case in cases:
            with self.subTest(case=case):
                project, _, _, request, render_manifest, review, _ = (
                    self.prepare_visual_finalization()
                )
                render_payload = json.loads(render_manifest.read_text(encoding="utf-8"))
                review_payload = json.loads(review.read_text(encoding="utf-8"))
                if case == "wrong_pdf":
                    render_payload["pdf_sha256"] = "0" * 64
                elif case == "missing_page":
                    render_payload["pages"].pop()
                elif case == "duplicate_page":
                    render_payload["pages"][-1]["page"] = 1
                elif case in ("arbitrary_bytes", "blank_png"):
                    first = project / render_payload["pages"][0]["path"]
                    if case == "arbitrary_bytes":
                        first.write_bytes(b"not a rendered PNG")
                    else:
                        write_render_png(first, blank=True)
                    render_payload["pages"][0]["sha256"] = sha256_file(first)
                elif case == "tampered_pdf":
                    (project / "iterations/v001/paper/paper.pdf").write_bytes(
                        b"tampered candidate"
                    )
                elif case == "tampered_request":
                    request.write_text(request.read_text(encoding="utf-8") + " ")
                elif case == "unknown_check":
                    review_payload["checklist"]["cropping"] = "unknown"
                elif case == "stale_project":
                    current_path = project / "current.json"
                    current = json.loads(current_path.read_text(encoding="utf-8"))
                    current["status"] = "stale"
                    current_path.write_text(json.dumps(current, sort_keys=True) + "\n")

                if case in {
                    "wrong_pdf",
                    "missing_page",
                    "duplicate_page",
                    "arbitrary_bytes",
                    "blank_png",
                }:
                    render_manifest.write_text(
                        json.dumps(render_payload, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    review_payload["render_manifest_sha256"] = sha256_file(render_manifest)
                if case == "unknown_check":
                    review.write_text(
                        json.dumps(review_payload, sort_keys=True) + "\n", encoding="utf-8"
                    )
                elif case in {
                    "wrong_pdf",
                    "missing_page",
                    "duplicate_page",
                    "arbitrary_bytes",
                    "blank_png",
                }:
                    review.write_text(
                        json.dumps(review_payload, sort_keys=True) + "\n", encoding="utf-8"
                    )

                with self.assertRaises(ValueError):
                    paper_production.finalize_paper(project, "v001", review)
                self.assertFalse(
                    (project / "iterations/v001/paper/paper_finalization.json").exists()
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

    def test_review_request_publish_failure_is_recoverable_without_recompile(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        original = paper_production._write_new_json
        manifest_path = project / "iterations/v001/paper/paper_manifest.json"

        def fail_request(path: Path, payload: object) -> None:
            if path.name == "visual_review_request.json":
                raise OSError("injected request publish failure")
            original(path, payload)

        with patch("paper_production._write_new_json", side_effect=fail_request):
            with self.assertRaises(OSError):
                produce_paper(
                    project,
                    "v001",
                    content,
                    environment,
                    template_path=None,
                    compiler=compiler,
                )
        self.assertTrue(manifest_path.is_file())
        manifest_bytes = manifest_path.read_bytes()
        self.assertFalse((manifest_path.parent / "visual_review_request.json").exists())
        recovered = recover_paper_publication(project, "v001")
        self.assertEqual("paper_visual_review_request", recovered["manifest_type"])
        request_path = manifest_path.parent / "visual_review_request.json"
        self.assertTrue(request_path.is_file())
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())
        request_path.write_text(request_path.read_text() + "tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            recover_paper_publication(project, "v001")

    def test_publication_receipt_precedes_and_binds_both_exact_public_files(self) -> None:
        project, content = self.make_project()
        compiler = self.make_compiler()
        environment = self.environment_manifest(project, compiler)
        observed: list[str] = []
        original = paper_production._write_new_bytes

        def record_publish(path: Path, data: bytes, label: str) -> None:
            if path.name in {
                "paper_publication_receipt.json",
                "paper_manifest.json",
                "visual_review_request.json",
            }:
                observed.append(path.name)
            original(path, data, label)

        with patch("paper_production._write_new_bytes", side_effect=record_publish):
            produce_paper(
                project,
                "v001",
                content,
                environment,
                template_path=None,
                compiler=compiler,
            )

        paper = project / "iterations/v001/paper"
        self.assertEqual(
            [
                "paper_publication_receipt.json",
                "paper_manifest.json",
                "visual_review_request.json",
            ],
            [name for name in observed if name in {
                "paper_publication_receipt.json",
                "paper_manifest.json",
                "visual_review_request.json",
            }],
        )
        receipt = json.loads(
            (paper / "paper_publication_receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual("paper_publication_transaction", receipt["manifest_type"])
        self.assertEqual(receipt["created_at"], receipt["transaction_created_at"])
        for key, filename in (
            ("paper_manifest", "paper_manifest.json"),
            ("visual_review_request", "visual_review_request.json"),
        ):
            record = receipt["outputs"][key]
            canonical = base64.b64decode(record["canonical_bytes_base64"], validate=True)
            public = (paper / filename).read_bytes()
            self.assertEqual(public, canonical)
            self.assertEqual(hashlib.sha256(public).hexdigest(), record["sha256"])
            self.assertEqual(len(public), record["byte_size"])
            self.assertEqual(json.loads(public), record["payload"])
            self.assertEqual(receipt["created_at"], record["created_at"])

    def test_receipt_manifest_and_request_failure_boundaries_fail_closed_or_recover(self) -> None:
        for status in ("pass", "needs_revision"):
            for boundary in ("receipt", "manifest", "request"):
                with self.subTest(status=status, boundary=boundary):
                    project, content = self.make_project()
                    compiler = self.make_compiler()
                    if status == "needs_revision":
                        compiler.with_suffix(".aux").write_text(
                            "\\newlabel{mm-body-start}{{1}{1}}\n"
                            "\\newlabel{mm-body-end}{{8}{20}}\n",
                            encoding="utf-8",
                        )
                    environment = self.environment_manifest(project, compiler)
                    names = {
                        "receipt": "paper_publication_receipt.json",
                        "manifest": "paper_manifest.json",
                        "request": "visual_review_request.json",
                    }
                    original = paper_production._write_new_bytes

                    def fail_boundary(path: Path, data: bytes, label: str) -> None:
                        if path.name == names[boundary]:
                            raise OSError(f"injected {boundary} boundary failure")
                        original(path, data, label)

                    with patch(
                        "paper_production._write_new_bytes", side_effect=fail_boundary
                    ):
                        with self.assertRaises(OSError):
                            produce_paper(
                                project,
                                "v001",
                                content,
                                environment,
                                template_path=None,
                                compiler=compiler,
                            )
                    paper = project / "iterations/v001/paper"
                    receipt_path = paper / "paper_publication_receipt.json"
                    manifest_path = paper / "paper_manifest.json"
                    request_path = paper / "visual_review_request.json"
                    if boundary == "receipt":
                        self.assertFalse(receipt_path.exists())
                        self.assertFalse(manifest_path.exists())
                        self.assertFalse(request_path.exists())
                        continue

                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    manifest_bytes = base64.b64decode(
                        receipt["outputs"]["paper_manifest"]["canonical_bytes_base64"],
                        validate=True,
                    )
                    request_bytes = base64.b64decode(
                        receipt["outputs"]["visual_review_request"][
                            "canonical_bytes_base64"
                        ],
                        validate=True,
                    )
                    before_passes = (
                        paper / "build/attempt-01/.fixture-pass-count"
                    ).read_text(encoding="utf-8")
                    existing_manifest = (
                        manifest_path.read_bytes() if manifest_path.exists() else None
                    )
                    recovered = recover_paper_publication(project, "v001")
                    self.assertEqual("paper_visual_review_request", recovered["manifest_type"])
                    self.assertEqual(manifest_bytes, manifest_path.read_bytes())
                    self.assertEqual(request_bytes, request_path.read_bytes())
                    if existing_manifest is not None:
                        self.assertEqual(existing_manifest, manifest_path.read_bytes())
                    self.assertEqual(
                        before_passes,
                        (paper / "build/attempt-01/.fixture-pass-count").read_text(
                            encoding="utf-8"
                        ),
                    )

    def test_publication_recovery_rejects_timestamp_receipt_and_state_tamper(self) -> None:
        cases = ("request_created_at", "receipt_created_at", "receipt_hash", "stale")
        for case in cases:
            with self.subTest(case=case):
                project, content = self.make_project()
                compiler = self.make_compiler()
                environment = self.environment_manifest(project, compiler)
                produce_paper(
                    project,
                    "v001",
                    content,
                    environment,
                    template_path=None,
                    compiler=compiler,
                )
                paper = project / "iterations/v001/paper"
                if case == "request_created_at":
                    request_path = paper / "visual_review_request.json"
                    request = json.loads(request_path.read_text(encoding="utf-8"))
                    request["created_at"] = "2026-08-28T23:59:59Z"
                    request_path.write_text(
                        json.dumps(request, sort_keys=True) + "\n", encoding="utf-8"
                    )
                elif case in ("receipt_created_at", "receipt_hash"):
                    receipt_path = paper / "paper_publication_receipt.json"
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if case == "receipt_created_at":
                        receipt["created_at"] = "2026-08-28T23:59:59Z"
                    else:
                        receipt["outputs"]["paper_manifest"]["sha256"] = "0" * 64
                    receipt_path.write_text(
                        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8",
                    )
                else:
                    current_path = project / "current.json"
                    current = json.loads(current_path.read_text(encoding="utf-8"))
                    current["status"] = "stale"
                    current_path.write_text(
                        json.dumps(current, sort_keys=True) + "\n", encoding="utf-8"
                    )
                with self.assertRaises(ValueError):
                    recover_paper_publication(project, "v001")


if __name__ == "__main__":
    unittest.main()
