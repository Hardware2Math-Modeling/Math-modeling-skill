from __future__ import annotations

import json
import importlib
import re
import struct
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from figure_qa import refresh_figure_status, validate_figure_manifest  # noqa: E402
from export_figure import export_figure  # noqa: E402
from manifest import sha256_file  # noqa: E402
from visual_qa import run_visual_qa  # noqa: E402

export_figure_module = importlib.import_module("export_figure")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _write_png(path: Path, *, width: int, height: int, dpi: int) -> None:
    pixels_per_metre = round(dpi / 0.0254)
    scanlines = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk("IHDR".encode("ascii"), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk("pHYs".encode("ascii"), struct.pack(">IIB", pixels_per_metre, pixels_per_metre, 1))
        + _png_chunk("IDAT".encode("ascii"), zlib.compress(scanlines))
        + _png_chunk("IEND".encode("ascii"), b"")
    )


class FigureQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        (self.project / "results").mkdir()
        (self.project / "figures").mkdir()
        (self.project / "manifests").mkdir()
        self.source = self.project / "results/q1.json"
        self.source.write_text('{"score": 0.75}\n', encoding="utf-8")
        (self.project / "figures/q1.pdf").write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Page/MediaBox[0 0 240.945 144]>>endobj\n%%EOF\n"
        )
        (self.project / "figures/q1.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="50mm"></svg>\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_manifest(
        self,
        *,
        role: str = "evidence",
        claim_type: str = "data",
    ) -> dict[str, object]:
        return {
            "schema_version": "1",
            "figure_id": "q1-main",
            "role": role,
            "question_id": "Q1",
            "claim_id": "claim-q1-01",
            "claim_type": claim_type,
            "exploratory_draft": False,
            "sources": [
                {
                    "path": "results/q1.json",
                    "sha256": sha256_file(self.source),
                }
            ],
            "outputs": [
                {"path": "figures/q1.pdf", "format": "pdf"},
                {"path": "figures/q1.svg", "format": "svg"},
            ],
            "axes": [
                {"id": "x", "label": "Time", "unit": "s"},
                {"id": "y", "label": "Response", "unit": "m"},
            ],
            "legend": {"present": False, "reason": "single series"},
            "caption": "Response over the measured interval.",
            "paper_reference": "Figure 1",
            "paper_width_mm": 85,
            "grayscale_status": "pass",
            "colorblind_status": "pass",
            "render_status": "pass",
            "status": "draft",
        }

    def make_png_manifest(self, dpi: int) -> dict[str, object]:
        output = self.project / "figures/q1.png"
        _write_png(output, width=1200, height=800, dpi=dpi)
        manifest = self.make_manifest()
        manifest["outputs"] = [
            {
                "path": "figures/q1.png",
                "format": "png",
                "width_px": 1200,
                "height_px": 800,
                "dpi_x": dpi,
                "dpi_y": dpi,
            }
        ]
        return manifest

    @property
    def manifest_without_claim(self) -> dict[str, object]:
        manifest = self.make_manifest()
        del manifest["claim_id"]
        return manifest

    def test_manifest_requires_claim_source_hash_role_and_outputs(self) -> None:
        errors = validate_figure_manifest(
            self.manifest_without_claim,
            project_root=self.project,
        )
        self.assertTrue(any("claim_id" in error for error in errors))

    def test_stale_source_hash_blocks_verified_status(self) -> None:
        manifest = self.make_manifest()
        manifest["status"] = "verified"
        self.source.write_text("changed", encoding="utf-8")
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("stale" in error for error in errors))

    def test_png_requires_dimensions_and_at_least_300_dpi(self) -> None:
        manifest = self.make_png_manifest(dpi=150)
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("DPI" in error for error in errors))

    def test_conceptual_figure_cannot_support_evidence_claim(self) -> None:
        manifest = self.make_manifest(role="conceptual", claim_type="data")
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(
            any("示意图" in error or "conceptual" in error for error in errors)
        )

    def test_safe_relative_source_and_output_paths_are_required(self) -> None:
        manifest = self.make_manifest()
        manifest["sources"] = [
            {"path": str(self.source), "sha256": sha256_file(self.source)}
        ]
        outputs = manifest["outputs"]
        self.assertIsInstance(outputs, list)
        outputs[0] = {"path": "../outside.pdf"}
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("relative" in error and "source" in error for error in errors))
        self.assertTrue(any("relative" in error and "output" in error for error in errors))

    def test_axes_units_and_legend_metadata_are_required(self) -> None:
        manifest = self.make_manifest()
        manifest["axes"] = [
            {"id": "x", "label": "", "unit": "s"},
            {"id": "y", "label": "Response", "unit": ""},
        ]
        del manifest["legend"]
        errors = validate_figure_manifest(manifest, project_root=self.project)
        for field in ("axes", "unit", "legend"):
            with self.subTest(field=field):
                self.assertTrue(any(field in error for error in errors))

    def test_malformed_output_fails_closed(self) -> None:
        (self.project / "figures/q1.pdf").write_bytes(b"not a pdf")
        errors = validate_figure_manifest(
            self.make_manifest(),
            project_root=self.project,
        )
        self.assertTrue(any("PDF" in error for error in errors))

    def test_pdf_requires_a_positive_media_box(self) -> None:
        (self.project / "figures/q1.pdf").write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Page/MediaBox[0 0 0 144]>>endobj\n%%EOF\n"
        )
        errors = validate_figure_manifest(self.make_manifest(), project_root=self.project)
        self.assertTrue(any("MediaBox" in error or "PDF page size" in error for error in errors))

    def test_svg_requires_nonzero_physical_dimensions(self) -> None:
        (self.project / "figures/q1.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="0mm" height="0mm"></svg>\n',
            encoding="utf-8",
        )
        errors = validate_figure_manifest(self.make_manifest(), project_root=self.project)
        self.assertTrue(any("SVG" in error and "dimension" in error for error in errors))

    def test_png_rejects_trailing_bytes_after_iend(self) -> None:
        manifest = self.make_png_manifest(dpi=300)
        output = self.project / "figures/q1.png"
        output.write_bytes(output.read_bytes() + b"JUNK")
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("trailing" in error for error in errors))

    def test_refresh_persists_verified_then_stale_without_accepting_new_hash(self) -> None:
        manifest_path = self.project / "manifests/q1-figure.json"
        manifest = self.make_manifest()
        expected_hash = manifest["sources"][0]["sha256"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        refreshed = refresh_figure_status(manifest_path, project_root=self.project)
        self.assertEqual("verified", refreshed["status"])

        self.source.write_text('{"score": 0.80}\n', encoding="utf-8")
        refreshed = refresh_figure_status(manifest_path, project_root=self.project)
        self.assertEqual("stale", refreshed["status"])
        self.assertEqual(expected_hash, refreshed["sources"][0]["sha256"])
        self.assertEqual(
            refreshed,
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )

    def test_refresh_never_verifies_figure_while_visual_review_is_pending(self) -> None:
        manifest_path = self.project / "manifests/q1-figure.json"
        manifest = self.make_manifest()
        manifest["grayscale_status"] = "needs_review"
        manifest["colorblind_status"] = "needs_review"
        manifest["render_status"] = "needs_review"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        refreshed = refresh_figure_status(manifest_path, project_root=self.project)

        self.assertEqual("needs_review", refreshed["status"])

    def test_exploratory_draft_is_the_only_claim_id_exception(self) -> None:
        manifest = self.make_manifest(role="diagnostic", claim_type="exploratory")
        manifest["claim_id"] = ""
        manifest["exploratory_draft"] = True
        self.assertEqual(
            [],
            validate_figure_manifest(manifest, project_root=self.project),
        )

    def test_export_refuses_to_draw_from_a_stale_registered_source(self) -> None:
        manifest_path = self.project / "manifests/q1-figure.json"
        manifest_path.write_text(json.dumps(self.make_manifest()), encoding="utf-8")
        self.source.write_text('{"score": 0.80}\n', encoding="utf-8")

        class MustNotDraw:
            def savefig(self, *_args: object, **_kwargs: object) -> None:
                self.fail("savefig must not run for stale input")

        figure = MustNotDraw()
        figure.fail = self.fail
        with self.assertRaisesRegex(ValueError, "stale"):
            export_figure(
                figure,
                source_result_path=Path("results/q1.json"),
                figure_manifest_path=Path("manifests/q1-figure.json"),
                project_root=self.project,
            )

    def test_export_applies_style_and_writes_registered_pdf_and_png(self) -> None:
        manifest = self.make_png_manifest(dpi=300)
        manifest["outputs"].insert(
            0,
            {"path": "figures/q1.pdf", "format": "pdf"},
        )
        manifest_path = self.project / "manifests/q1-figure.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.project / "figures/q1.pdf").unlink()
        (self.project / "figures/q1.png").unlink()

        style_state = {"active": False}

        class Style:
            @staticmethod
            def use(path: object) -> None:
                self.assertTrue(Path(path).is_file())
                style_state["active"] = True

        matplotlib = types.ModuleType("matplotlib")
        matplotlib.style = Style()

        class FixtureFigure:
            def savefig(self, path: object, **kwargs: object) -> None:
                self.assertTrue(style_state["active"])
                target = Path(path)
                if target.suffix == ".pdf":
                    target.write_bytes(
                        b"%PDF-1.4\n1 0 obj<</Type/Page/MediaBox[0 0 240.945 144]>>endobj\n%%EOF\n"
                    )
                elif target.suffix == ".png":
                    _write_png(target, width=1200, height=800, dpi=int(kwargs["dpi"]))
                else:
                    self.fail(f"unexpected export format: {target.suffix}")

        figure = FixtureFigure()
        figure.assertTrue = self.assertTrue
        figure.fail = self.fail
        with patch.dict(sys.modules, {"matplotlib": matplotlib}):
            refreshed = export_figure_module.export_figure(
                figure,
                source_result_path=Path("results/q1.json"),
                figure_manifest_path=Path("manifests/q1-figure.json"),
                project_root=self.project,
            )

        self.assertEqual("verified", refreshed["status"])
        self.assertTrue((self.project / "figures/q1.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertTrue((self.project / "figures/q1.png").read_bytes().startswith(b"\x89PNG"))

    def test_export_rolls_back_all_outputs_when_a_later_publish_fails(self) -> None:
        manifest = self.make_png_manifest(dpi=300)
        manifest["outputs"].insert(0, {"path": "figures/q1.pdf", "format": "pdf"})
        manifest_path = self.project / "manifests/q1-figure.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        old_pdf = b"%PDF-1.4\nold-pdf\n%%EOF\n"
        old_png = (self.project / "figures/q1.png").read_bytes()
        (self.project / "figures/q1.pdf").write_bytes(old_pdf)

        style_state = {"active": False}

        class Style:
            @staticmethod
            def use(path: object) -> None:
                style_state["active"] = Path(path).is_file()

        matplotlib = types.ModuleType("matplotlib")
        matplotlib.style = Style()

        class FixtureFigure:
            def savefig(self, path: object, **kwargs: object) -> None:
                self.assertTrue(style_state["active"])
                target = Path(path)
                if target.suffix == ".pdf":
                    target.write_bytes(
                        b"%PDF-1.4\n1 0 obj<</Type/Page/MediaBox[0 0 240.945 144]>>endobj\nnew-pdf\n%%EOF\n"
                    )
                elif target.suffix == ".png":
                    _write_png(target, width=1200, height=800, dpi=int(kwargs["dpi"]))

        figure = FixtureFigure()
        figure.assertTrue = self.assertTrue
        call_count = {"value": 0}
        real_replace = export_figure_module.os.replace

        def fail_on_later_publish(source: object, target: object) -> None:
            call_count["value"] += 1
            if call_count["value"] == 2:
                raise OSError("simulated later publish failure")
            real_replace(source, target)

        with (
            patch.dict(sys.modules, {"matplotlib": matplotlib}),
            patch.object(export_figure_module.os, "replace", side_effect=fail_on_later_publish),
            self.assertRaisesRegex(OSError, "simulated later publish failure"),
        ):
            export_figure_module.export_figure(
                figure,
                source_result_path=Path("results/q1.json"),
                figure_manifest_path=Path("manifests/q1-figure.json"),
                project_root=self.project,
            )

        self.assertEqual(old_pdf, (self.project / "figures/q1.pdf").read_bytes())
        self.assertEqual(old_png, (self.project / "figures/q1.png").read_bytes())
        self.assertEqual([], list((self.project / "figures").glob(".q1.*")))

    def test_style_uses_hash_prefix_for_every_six_digit_hex_color(self) -> None:
        style_path = ROOT / "skills/math-modeling-visualization/assets/styles/modeling.mplstyle"
        text = style_path.read_text(encoding="utf-8")
        palette = re.search(r"axes\.prop_cycle:\s*cycler\(color=\[(.*?)\]\)", text)
        self.assertIsNotNone(palette)
        self.assertGreaterEqual(len(re.findall(r"#[0-9A-Fa-f]{6}", palette.group(1))), 6)
        for line_number, line in enumerate(text.splitlines(), start=1):
            value = line.partition(":")[2]
            with self.subTest(line=line_number):
                self.assertNotRegex(value, r"(?<!#)\b[0-9A-Fa-f]{6}\b")

    def test_visualization_agent_metadata_is_present_and_discoverable(self) -> None:
        metadata_path = ROOT / "skills/math-modeling-visualization/agents/openai.yaml"
        self.assertTrue(metadata_path.is_file())
        metadata = metadata_path.read_text(encoding="utf-8")
        self.assertIn("$math-modeling-visualization", metadata)
        self.assertRegex(metadata, r"(?m)^\s*allow_implicit_invocation:\s*true\s*$")

    def test_visual_qa_reports_missing_renderer_as_needs_review(self) -> None:
        result = run_visual_qa(
            self.make_manifest(),
            project_root=self.project,
            pdftoppm_executable=self.project / "missing-pdftoppm",
        )
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("needs_review", result["render_status"])
        self.assertTrue(any("pdftoppm" in item for item in result["messages"]))

    def test_visual_qa_rejects_raster_too_narrow_for_paper_width(self) -> None:
        manifest = self.make_png_manifest(dpi=300)
        _write_png(
            self.project / "figures/q1.png",
            width=600,
            height=800,
            dpi=300,
        )
        manifest["outputs"][0]["width_px"] = 600
        result = run_visual_qa(manifest, project_root=self.project)
        self.assertEqual("needs_review", result["status"])
        self.assertTrue(any("paper width" in item for item in result["messages"]))


if __name__ == "__main__":
    unittest.main()
