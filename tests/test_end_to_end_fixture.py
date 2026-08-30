from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from authorization_capability import _HOST_REGISTRATION_TOKEN, _install_host_capability
from figure_qa import refresh_figure_status
from manifest import sha256_file
from paper_content import freeze_content, validate_paper_content
from paper_production import produce_paper
from result_contract import validate_result_payload
from project_state import (
    create_iteration,
    init_project,
    load_current,
    mark_stale,
    record_gate,
)
from python_runner import run_python
from test_latex_qa import write_text_pdf

FIXTURE = ROOT / "tests/fixtures/cumcm-mini"


def gate_status(project: Path, gate_id: str) -> object:
    return json.loads((project / "current.json").read_text(encoding="utf-8"))["gates"][gate_id]


def cannot_route(project: Path, stage: str) -> bool:
    gate_id = {
        "model-construction": "gate1",
        "model-solving": "gate2",
    }.get(stage)
    if gate_id is None:
        return False
    return gate_status(project, gate_id) != "confirmed"


def figure_status(project: Path, figure_id: str) -> object:
    path = project / f"iterations/v001/manifests/{figure_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))["status"]


def validation_status(project: Path) -> object:
    path = project / "iterations/v001/state/handoff.json"
    return json.loads(path.read_text(encoding="utf-8"))["state"]["validation_status"]


def paper_content_status(project: Path) -> object:
    path = project / "iterations/v001/paper/frozen-content.json"
    return json.loads(path.read_text(encoding="utf-8"))["status"]


def paper_manifest(project: Path) -> dict[str, object]:
    path = project / "iterations/v001/paper/paper_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _compiler_on_host() -> tuple[str, Path] | None:
    for name in ("tectonic", "latexmk", "xelatex"):
        candidate = shutil.which(name)
        if candidate:
            return name, Path(candidate).resolve()
    return None


def _png(
    path: Path,
    series: list[dict[str, object]],
    width: int = 1200,
    height: int = 800,
) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    pixels = bytearray(b"\xff" * (width * height * 3))

    def put(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset:offset + 3] = bytes(color)

    def line(
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        x0, y0 = start
        x1, y1 = end
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            put(x0, y0, color)
            if (x0, y0) == (x1, y1):
                break
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    months = [float(point["month"]) for point in series]
    actual = [float(point["actual_items"]) for point in series]
    fitted = [float(point["fitted_items"]) for point in series]
    x_min, x_max = min(months), max(months)
    y_min, y_max = min([*actual, *fitted]), max([*actual, *fitted])
    left, right, top, bottom = 100, width - 100, 80, height - 80

    def coordinate(month: float, value: float) -> tuple[int, int]:
        x = left + round((month - x_min) * (right - left) / (x_max - x_min))
        y = bottom - round((value - y_min) * (bottom - top) / (y_max - y_min))
        return x, y

    line((left, top), (left, bottom), (64, 64, 64))
    line((left, bottom), (right, bottom), (64, 64, 64))
    fitted_points = [
        coordinate(month, value) for month, value in zip(months, fitted)
    ]
    for start, end in zip(fitted_points, fitted_points[1:]):
        line(start, end, (0, 0, 0))
    for month, value in zip(months, actual):
        x, y = coordinate(month, value)
        for offset_y in range(-3, 4):
            for offset_x in range(-3, 4):
                put(x + offset_x, y + offset_y, (128, 128, 128))

    ppm = round(300 / 0.0254)
    rows = b"".join(
        b"\x00" + bytes(pixels[row * width * 3:(row + 1) * width * 3])
        for row in range(height)
    )
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _result(
    question: str,
    metric_name: str,
    metric: dict[str, object],
    output_path: str,
    output_hash: str,
    run_id: str,
    run_manifest_path: str,
    run_manifest_hash: str,
) -> dict[str, object]:
    suffix = question.lower()
    value = metric["value"]
    unit = metric["unit"]
    return {
        "question_id": question,
        "model_id": f"model-{suffix}-v1",
        "assumptions": ["fixture/test-data：测试数据假设成立。"],
        "baseline": {"model_id": f"baseline-{suffix}", "metric": metric_name, "value": value, "unit": unit},
        "parameters": {"seed": {"value": 1729, "unit": "dimensionless"}},
        "metrics": {metric_name: {"value": value, "unit": unit, "source_path": output_path, "source_hash": output_hash, "finite": True}},
        "units": {metric_name: unit},
        "run_manifest": {"run_id": run_id, "status": "success", "seed": 1729, "path": run_manifest_path, "sha256": run_manifest_hash},
        "validation_plan": {"validation_cycle_id": f"validation-{suffix}-001", "threshold": 0.5, "split": "holdout", "scope": f"{question} test observations", "seed": 1729, "method": "blocked holdout"},
        "validation_history": [],
        "validation_manifest": {"validation_cycle_id": f"validation-{suffix}-001", "status": "pass"},
        "figure_manifests": [],
        "claims": [{"claim_id": f"claim-{suffix}-01", "statement": f"{question} 运行结果的 {metric_name} 为 {format(value, '.12g')} {unit}。", "metric": metric_name, "source_path": output_path, "source_hash": output_hash}],
        "freeze_status": "confirmed",
    }


class _Verifier:
    def __init__(self, receipt: dict[str, object]): self.receipt = receipt
    def verify_user_event(self, *, event_id: str, event_type: str, challenge_sha256: str):
        if self.receipt.get("event_id") == event_id and self.receipt.get("event_type") == event_type and self.receipt.get("challenge_sha256") == challenge_sha256:
            return dict(self.receipt)
        return None


class EndToEndFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.input = self.root / "input"
        shutil.copytree(FIXTURE / "input", self.input)
        self.project = self.root / "project"
        init_project(self.project, python_executable=Path(sys.executable).resolve(), input_dir=self.input, template_path=None)
        self.iteration = self.project / "iterations/v001"

    def tearDown(self) -> None: self.tmp.cleanup()

    def _gate(self, gate_id: str, kind: str, path: Path, event: str) -> None:
        digest = sha256_file(path)
        scope = [{"path": path.relative_to(self.project).as_posix(), "kind": kind, "sha256": digest}]
        from handoff_schema import user_event_challenge_sha256
        challenge = user_event_challenge_sha256("gate-confirmation", {"schema_version": "2", "gate_id": gate_id, "artifact_scope": scope})
        receipt = {"schema_version": "2", "provenance_type": "trusted_user_event", "provider": "fixture-host-boundary", "event_id": event, "event_type": "gate-confirmation", "actor_id": "tester", "occurred_at": "2026-08-27T00:00:00Z", "challenge_sha256": challenge}
        cap = _install_host_capability(verify_user_event=_Verifier(receipt).verify_user_event, verify_official_source=lambda **_: False, registration_token=_HOST_REGISTRATION_TOKEN)
        record_gate(self.project, gate_id=gate_id, status="confirmed", confirmer="tester", artifact_hashes=[digest], artifact_scope=scope, note="fixture review", confirmation_event_id=event, host_capability=cap)

    def _compiler(self, exit_code: int = 0) -> Path:
        compiler = self.root / f"compiler-{exit_code}.py"
        fixture_pdf = compiler.with_suffix(".pdf")
        write_text_pdf(fixture_pdf, 26)
        compiler.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "flag = '--outdir' if '--outdir' in args else '-output-directory'\n"
            "out = pathlib.Path(args[args.index(flag) + 1])\n"
            "out.mkdir(parents=True, exist_ok=True)\n"
            f"if {exit_code} == 0:\n"
            "    shutil.copyfile(pathlib.Path(__file__).with_suffix('.pdf'), out / 'main.pdf')\n"
            "    (out / 'main.aux').write_text('\\\\newlabel{mm-body-start}{{1}{1}}\\n\\\\newlabel{mm-body-end}{{8}{1}}\\n')\n"
            "    (out / 'main.log').write_text('fixture compiler log\\n')\n"
            "print('fixture compiler stderr', file=sys.stderr)\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        compiler.chmod(compiler.stat().st_mode | 0o100)
        return compiler

    def _environment(self, compiler: Path, *, validation: str = "pass") -> Path:
        compiler_name = compiler.name if compiler.name in {"tectonic", "latexmk", "xelatex"} else "xelatex"
        engine = "tectonic" if compiler_name == "tectonic" else "xelatex"
        path = self.project / "qa/environment.json"
        payload = {
            "status": "pass",
            "project_root": str(self.project),
            "python": {"status": "pass", "path": str(Path(sys.executable).resolve())},
            "packages": [],
            "latex": {
                "status": "pass",
                "selected": engine,
                "tools": [{"name": compiler_name, "status": "available", "path": str(compiler), "sha256": sha256_file(compiler), "version": "fixture compiler 1"}],
                "message": "fixture/test-data",
            },
            "pdf_renderer": {"name": "pdftoppm", "status": "not_supplied", "path": None, "sha256": None, "version_command": None, "version_exit_code": None, "version_signature": None, "version_output": None, "version_output_sha256": None, "trust_basis": "fixture/test-data"},
            "template": {"status": "fallback_non_submission"},
            "blockers": [],
            "warnings": [],
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        handoff = {"state": {"validation_status": validation, "invalidated_stages": []}, "artifacts": [{"path": "qa/environment.json", "kind": "environment", "description": "fixture/test-data environment", "sha256": sha256_file(path)}]}
        (self.iteration / "state/handoff.json").write_text(json.dumps(handoff, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _run_workflow(
        self,
        *,
        compiler_exit: int = 0,
        validation: str = "pass",
        propagate_stale: bool = True,
        create_mixed_iteration: bool = True,
    ) -> tuple[Path, Path]:
        self.assertEqual("pending", gate_status(self.project, "gate1"))
        self.assertTrue(cannot_route(self.project, "model-construction"))
        self.assertRaises(ValueError, record_gate, self.project, gate_id="gate1", status="confirmed", confirmer="tester", artifact_hashes=[], note="bad")
        pa = self.iteration / "state/problem-analysis.json"; pa.write_text('{"fixture":true}\n')
        ms = self.iteration / "state/model-specification.json"; ms.write_text('{"fixture":true}\n')
        self._gate("gate1", "problem-analysis", pa, "fixture-g1")
        self.assertFalse(cannot_route(self.project, "model-construction"))
        self.assertTrue(cannot_route(self.project, "model-solving"))
        self._gate("gate2", "model-specification", ms, "fixture-g2")
        self.assertFalse(cannot_route(self.project, "model-solving"))
        for q in ("q1", "q2"):
            out = self.iteration / f"results/{q}-run"; out.mkdir()
            script = FIXTURE / "scripts" / f"{q}.py"
            run_python(Path(sys.executable).resolve(), script, cwd=self.project, output_dir=out, input_paths=[self.project / "input/data.csv"], seed=1729, timeout_seconds=30, cli_mode="json_io", input_path=self.project / "input/data.csv", output_path=out / "output.json")
            output = json.loads((out / "output.json").read_text(encoding="utf-8"))
            self.assertEqual("fixture/test-data", output["fixture_label"])
            self.assertEqual(1729, output["seed"])
            for metric in output["metrics"].values():
                self.assertIsInstance(metric["value"], (int, float))
                self.assertTrue(math.isfinite(metric["value"]))
                self.assertIn("unit", metric)
            metric_name = {"q1": "r_squared", "q2": "total_cost"}[q]
            runner_output_path = f"results/{q}-run/output.json"
            runner_output_hash = sha256_file(out / "output.json")
            run_manifest = out / "run_manifest.json"
            result = self.iteration / f"results/{q}-result.json"
            result.write_text(
                json.dumps(
                    _result(
                        q.upper(),
                        metric_name,
                        output["metrics"][metric_name],
                        runner_output_path,
                        runner_output_hash,
                        f"run-{q}-001",
                        f"results/{q}-run/run_manifest.json",
                        sha256_file(run_manifest),
                    ),
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result_payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual([], validate_result_payload(result_payload))
            self.assertIn("fixture/test-data", result_payload["assumptions"][0])
            runner_metric = output["metrics"][metric_name]
            self.assertEqual([metric_name], list(result_payload["metrics"]))
            result_metric = result_payload["metrics"][metric_name]
            self.assertEqual(runner_metric["value"], result_metric["value"])
            self.assertEqual(runner_metric["unit"], result_metric["unit"])
            self.assertEqual(runner_output_path, result_metric["source_path"])
            self.assertEqual(runner_output_hash, result_metric["source_hash"])
            result_claim = result_payload["claims"][0]
            self.assertEqual(metric_name, result_claim["metric"])
            self.assertEqual(runner_output_path, result_claim["source_path"])
            self.assertEqual(runner_output_hash, result_claim["source_hash"])
        q1_output = self.iteration / "results/q1-run/output.json"
        q1_payload = json.loads(q1_output.read_text(encoding="utf-8"))
        figdir = self.iteration / "figures"
        _png(figdir / "q1-fit.png", q1_payload["series"])
        fm = self.iteration / "manifests/q1-fit.json"
        fm.write_text(json.dumps({"schema_version":"1","figure_id":"q1-fit","role":"evidence","question_id":"Q1","claim_id":"claim-q1-01","claim_type":"data","exploratory_draft":False,"sources":[{"path":"results/q1-run/output.json","sha256":sha256_file(q1_output)}],"outputs":[{"path":"figures/q1-fit.png","format":"png","width_px":1200,"height_px":800,"dpi_x":300,"dpi_y":300}],"axes":[{"id":"x","label":"month","unit":"month"},{"id":"y","label":"demand","unit":"items"}],"legend":{"present":True,"labels":["actual items","fitted items"]},"caption":f"Q1 actual and fitted demand from {len(q1_payload['series'])} regression points; fixture/test-data","paper_reference":"Figure 1","paper_width_mm":85,"grayscale_status":"pass","colorblind_status":"pass","render_status":"pass","status":"draft"}, ensure_ascii=False))
        self.assertEqual("verified", refresh_figure_status(fm, project_root=self.iteration)["status"])
        self.assertEqual("verified", figure_status(self.project, "q1-fit"))
        q1_result_path = self.iteration / "results/q1-result.json"
        q1_result_with_figure = json.loads(
            q1_result_path.read_text(encoding="utf-8")
        )
        q1_result_with_figure["figure_manifests"] = [{
            "figure_id": "q1-fit",
            "status": "verified",
            "manifest_path": "manifests/q1-fit.json",
            "manifest_hash": sha256_file(fm),
        }]
        q1_result_path.write_text(
            json.dumps(q1_result_with_figure, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        png_bytes = (figdir / "q1-fit.png").read_bytes()
        idat_offset = png_bytes.index(b"IDAT")
        idat_length = struct.unpack(">I", png_bytes[idat_offset - 4:idat_offset])[0]
        raw_rows = zlib.decompress(
            png_bytes[idat_offset + 4:idat_offset + 4 + idat_length]
        )
        row_width = 1200 * 3
        pixel_values: set[bytes] = set()
        for row_index in range(800):
            row_start = row_index * (row_width + 1) + 1
            for column in range(0, row_width, 3):
                pixel_values.add(raw_rows[row_start + column:row_start + column + 3])
                if len(pixel_values) > 1:
                    break
            if len(pixel_values) > 1:
                break
        self.assertGreater(len(pixel_values), 1, "Q1 PNG must contain data-derived pixels")
        q1_result = self.iteration / "results/q1-result.json"
        q1_result_payload = json.loads(q1_result.read_text(encoding="utf-8"))
        self.assertEqual(
            [{
                "figure_id": "q1-fit",
                "status": "verified",
                "manifest_path": "manifests/q1-fit.json",
                "manifest_hash": sha256_file(fm),
            }],
            q1_result_payload["figure_manifests"],
        )
        self.assertEqual([], validate_result_payload(q1_result_payload))
        (self.iteration / "state/handoff.json").write_text(json.dumps({"state":{"validation_status":"pass","invalidated_stages":[]},"artifacts":[]}) + "\n")
        vm = self.iteration / "manifests/validation.json"; vm.write_text('{"validation_cycle_id":"v1","status":"pass","fixture_label":"fixture/test-data"}\n')
        self.assertEqual("fixture/test-data", json.loads(vm.read_text())["fixture_label"])
        from handoff_schema import user_event_challenge_sha256
        scope = [
            {
                "path": path.relative_to(self.project).as_posix(),
                "kind": kind,
                "sha256": sha256_file(path),
            }
            for path, kind in (
                (self.iteration / "results/q1-result.json", "result-contract"),
                (self.iteration / "results/q2-result.json", "result-contract"),
                (self.iteration / "results/q1-run/run_manifest.json", "run-manifest"),
                (self.iteration / "results/q2-run/run_manifest.json", "run-manifest"),
                (vm, "validation-manifest"),
                (fm, "figure-manifest"),
            )
        ]
        ordered = sorted(scope, key=lambda x: (x["kind"], x["path"]))
        challenge = user_event_challenge_sha256("gate-confirmation", {"schema_version":"2", "gate_id":"gate3", "artifact_scope":ordered})
        receipt = {"schema_version":"2","provenance_type":"trusted_user_event","provider":"fixture-host-boundary","event_id":"fixture-g3","event_type":"gate-confirmation","actor_id":"tester","occurred_at":"2026-08-27T00:00:00Z","challenge_sha256":challenge}
        cap = _install_host_capability(verify_user_event=_Verifier(receipt).verify_user_event, verify_official_source=lambda **_:False, registration_token=_HOST_REGISTRATION_TOKEN)
        record_gate(self.project, gate_id="gate3", status="confirmed", confirmer="tester", artifact_hashes=[e["sha256"] for e in ordered], artifact_scope=scope, note="fixture review", confirmation_event_id="fixture-g3", host_capability=cap)
        expected_gate3_scope = sorted(
            [
                {
                    "path": path.relative_to(self.project).as_posix(),
                    "kind": kind,
                    "sha256": sha256_file(path),
                }
                for path, kind in (
                    (self.iteration / "results/q1-result.json", "result-contract"),
                    (self.iteration / "results/q2-result.json", "result-contract"),
                    (self.iteration / "results/q1-run/run_manifest.json", "run-manifest"),
                    (self.iteration / "results/q2-run/run_manifest.json", "run-manifest"),
                    (vm, "validation-manifest"),
                    (fm, "figure-manifest"),
                )
            ],
            key=lambda entry: (entry["kind"], entry["path"]),
        )
        gate_report = json.loads(
            (self.project / "qa/gates.json").read_text(encoding="utf-8")
        )
        self.assertEqual(expected_gate3_scope, gate_report["records"][-1]["artifact_scope"])
        content = {"schema_version":"1","language":"zh-CN","requirement_manifests":[],"abstract":{"intro_sentences":["测试问题。","本文完成验证。"],"question_paragraphs":[{"question_id":"Q1","leading_summary":"回归分析。","modeling_steps":"建立模型。","answer":"结果有效。"},{"question_id":"Q2","leading_summary":"资源分配。","modeling_steps":"建立约束。","answer":"成本最小。"}]},"keywords":["数学建模"],"sections":{"1":{"title":"问题背景与重述","subsections":{"1.1":{"title":"问题背景","content":"测试。"},"1.2":{"title":"问题重述","content":"测试。"}}},"2":{"title":"问题分析","content":"测试。"},"3":{"title":"模型假设","content":"测试。"},"4":{"title":"符号说明","content":"测试。"},"5":{"title":"模型的建立与求解","questions":[{"question_id":"Q1","title":"第一问","subsections":{"5.1.1":{"title":"建模","content":"测试。"},"5.1.2":{"title":"计算","content":"测试。"}}},{"question_id":"Q2","title":"第二问","subsections":{"5.2.1":{"title":"建模","content":"测试。"},"5.2.2":{"title":"计算","content":"测试。"}}}]},"6":{"title":"模型检验","content":"测试。"},"7":{"title":"模型评价与推广/改进","content":"测试。"},"8":{"title":"结论","content":"测试。"}},"symbols":[{"symbol":"x","description":"变量","unit":"无量纲"}],"claims":[{"question_id":"Q1","claim_id":"claim-q1-01","statement":"结果。","source_path":"results/q1-result.json","source_hash":sha256_file(self.iteration/'results/q1-result.json'),"important":True},{"question_id":"Q2","claim_id":"claim-q2-01","statement":"结果。","source_path":"results/q2-result.json","source_hash":sha256_file(self.iteration/'results/q2-result.json'),"important":True}],"figure_references":[],"table_references":[],"references":[],"code_appendix":[],"ai_use_disclosure":[],"human_review_records":[],"supplemental_appendix":[]}
        content["keywords"].append("fixture/test-data")
        self.assertIn("fixture/test-data", content["keywords"])
        for index, question in enumerate(("q1", "q2")):
            result_payload = json.loads(
                (self.iteration / f"results/{question}-result.json").read_text(
                    encoding="utf-8"
                )
            )
            content["claims"][index]["statement"] = result_payload["claims"][0][
                "statement"
            ]
        content["figure_references"] = [{
            "figure_id": "q1-fit",
            "manifest_path": "manifests/q1-fit.json",
            "manifest_hash": sha256_file(fm),
        }]
        for index, (question, metric_name) in enumerate(
            (("q1", "r_squared"), ("q2", "total_cost"))
        ):
            result_payload = json.loads(
                (self.iteration / f"results/{question}-result.json").read_text(
                    encoding="utf-8"
                )
            )
            runner_payload = json.loads(
                (self.iteration / f"results/{question}-run/output.json").read_text(
                    encoding="utf-8"
                )
            )
            paper_statement = content["claims"][index]["statement"]
            self.assertEqual(result_payload["claims"][0]["statement"], paper_statement)
            self.assertIn(metric_name, paper_statement)
            self.assertIn(
                format(runner_payload["metrics"][metric_name]["value"], ".12g"),
                paper_statement,
            )
            self.assertIn(runner_payload["metrics"][metric_name]["unit"], paper_statement)
        self.assertEqual(
            [{
                "figure_id": "q1-fit",
                "manifest_path": "manifests/q1-fit.json",
                "manifest_hash": sha256_file(fm),
            }],
            content["figure_references"],
        )
        self.assertEqual([], validate_paper_content(content, evidence_root=self.iteration))
        freeze_content(content, output_path=self.iteration/'paper/frozen-content.json', evidence_root=self.iteration)
        self.assertEqual("complete", paper_content_status(self.project))
        compiler = self._compiler(exit_code=compiler_exit)
        env = self._environment(compiler, validation=validation)
        if not propagate_stale:
            return compiler, env
        data_path = self.project / "input/data.csv"
        data_path.write_text(data_path.read_text(encoding="utf-8") + "7,150,90,72,4.0,5.5\n", encoding="utf-8")
        mark_stale(self.project, changed_paths=["input/data.csv"], question_ids=["Q2"])
        stale = json.loads((self.project / "qa/staleness.json").read_text(encoding="utf-8"))
        self.assertEqual(["run", "figure", "validation", "paper"], stale["invalidated"]["Q2"])
        current = load_current(self.project)
        self.assertEqual("stale", current["status"])
        if create_mixed_iteration:
            create_iteration(self.project, reason="revise Q2", affected_questions=["Q2"])
            current = load_current(self.project)
            self.assertEqual("v001", current["question_sources"]["Q1"])
            self.assertEqual("v002", current["question_sources"]["Q2"])
        return compiler, env

    def test_offline_workflow_and_staleness(self) -> None:
        compiler, env = self._run_workflow(propagate_stale=False)
        report = produce_paper(
            self.project,
            "v001",
            self.iteration / "paper/frozen-content.json",
            env,
            compiler=compiler,
        )
        self.assertIn(report["status"], ("pass", "needs_revision"))
        self.assertEqual(
            "fallback_non_submission",
            paper_manifest(self.project)["template_status"],
        )
        self.assertFalse(paper_manifest(self.project)["submission_ready"])
        mark_stale(
            self.project,
            changed_paths=["input/data.csv"],
            question_ids=["Q2"],
        )
        current = load_current(self.project)
        self.assertEqual("stale", current["status"])
        create_iteration(
            self.project,
            reason="revise Q2",
            affected_questions=["Q2"],
        )
        current = load_current(self.project)
        self.assertEqual("v001", current["question_sources"]["Q1"])
        self.assertEqual("v002", current["question_sources"]["Q2"])

    def test_stale_propagation_mutates_input_and_invalidates_q2(self) -> None:
        self._run_workflow(create_mixed_iteration=False)
        self.assertIn(
            "7,150,90,72,4.0,5.5",
            (self.project / "input/data.csv").read_text(encoding="utf-8"),
        )
        stale = json.loads(
            (self.project / "qa/staleness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            ["run", "figure", "validation", "paper"],
            stale["invalidated"]["Q2"],
        )
        current = load_current(self.project)
        self.assertEqual("stale", current["status"])
        self.assertEqual("v001", current["question_sources"]["Q1"])
        create_iteration(self.project, reason="revise Q2", affected_questions=["Q2"])
        current = load_current(self.project)
        self.assertEqual("v001", current["question_sources"]["Q1"])
        self.assertEqual("v002", current["question_sources"]["Q2"])

    def test_failed_validation_blocks_compiler(self) -> None:
        compiler, env = self._run_workflow(
            validation="needs_revision",
            propagate_stale=False,
        )
        self.assertEqual("needs_revision", validation_status(self.project))
        self.assertRaises(ValueError, produce_paper, self.project, "v001", self.iteration / "paper/frozen-content.json", env, compiler=compiler)
        self.assertFalse((self.iteration / "paper/logs").exists())

    def test_failed_compiler_writes_log_and_non_ready_manifest(self) -> None:
        compiler, env = self._run_workflow(
            compiler_exit=7,
            propagate_stale=False,
        )
        report = produce_paper(self.project, "v001", self.iteration / "paper/frozen-content.json", env, compiler=compiler)
        self.assertEqual("fail", report["status"])
        self.assertFalse(report["submission_ready"])
        logs = list((self.iteration / "paper/logs").glob("*.log"))
        self.assertTrue(logs)
        self.assertIn("fixture compiler stderr", logs[0].read_text(encoding="utf-8"))

    def test_real_compiler_smoke_when_available(self) -> None:
        detected = _compiler_on_host()
        if detected is None:
            self.skipTest("no supported compiler available")
        name, compiler = detected
        template = self.root / "real-compiler-template"
        shutil.copytree(FIXTURE / "template", template)
        main = template / "main.tex"
        main.write_text(
            main.read_text(encoding="utf-8").replace(
                r"\documentclass{ctexart}",
                r"\documentclass[fontset=none]{ctexart}",
            ),
            encoding="utf-8",
        )
        for generated in (
            "paper-frontmatter.tex",
            "paper-body.tex",
            "paper-appendices.tex",
        ):
            (template / generated).write_text(
                "Fixture/test-data real compiler smoke.\n",
                encoding="utf-8",
            )
        build = template / "build"
        build.mkdir()
        if name == "tectonic":
            command = [str(compiler), "--outdir", str(build), str(main)]
        elif name == "latexmk":
            command = [
                str(compiler),
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                f"-outdir={build}",
                str(main),
            ]
        else:
            command = [
                str(compiler),
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-output-directory",
                str(build),
                str(main),
            ]
        completed = subprocess.run(
            command,
            cwd=template,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        pdf = build / "main.pdf"
        self.assertTrue(pdf.is_file())


if __name__ == "__main__": unittest.main()
