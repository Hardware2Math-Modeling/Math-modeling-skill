from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

from latex_qa import evaluate_page_gate, inspect_pdf  # noqa: E402


def write_text_pdf(path: Path, pages: int) -> None:
    """Write a small, structurally valid PDF with visible text on every page."""

    objects: list[bytes] = []
    page_ids = [3 + index * 2 for index in range(pages)]
    font_id = 3 + pages * 2
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{object_id} 0 R" for object_id in page_ids)
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode("ascii")
    )
    for index, page_id in enumerate(page_ids, start=1):
        content_id = page_id + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        stream = f"BT /F1 12 Tf 72 720 Td (Page {index}) Tj ET".encode("ascii")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(output)


def write_xref_stream_pdf(path: Path) -> None:
    """Write a one-page PDF 1.5 file whose cross-reference is a stream."""

    values = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length 38 >>\nstream\nBT /F1 12 Tf 72 720 Td (Page) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, value in enumerate(values, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    offsets.append(xref_offset)
    entries = b"\x00\x00\x00\x00\x00\xff\xff" + b"".join(
        b"\x01" + offset.to_bytes(4, "big") + b"\x00\x00"
        for offset in offsets[1:]
    )
    output.extend(
        (
            f"6 0 obj\n<< /Type /XRef /Size 7 /Root 1 0 R "
            f"/W [1 4 2] /Length {len(entries)} >>\nstream\n"
        ).encode("ascii")
    )
    output.extend(entries)
    output.extend(b"\nendstream\nendobj\n")
    output.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    path.write_bytes(output)


class LatexQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_total_pages_over_30_fails_closed_and_body_range_is_recorded(self) -> None:
        qa = evaluate_page_gate(
            total_pages=31,
            body_pages=26,
            body_start=2,
            body_end=27,
        )
        self.assertEqual("fail", qa["status"])
        self.assertIn("30", " ".join(qa["failed_checks"]))
        self.assertEqual({"start": 2, "end": 27, "pages": 26}, qa["body_range"])

    def test_body_below_target_is_revision_without_padding_advice(self) -> None:
        qa = evaluate_page_gate(
            total_pages=20,
            body_pages=18,
            body_start=2,
            body_end=19,
        )
        self.assertEqual("needs_revision", qa["status"])
        actions = " ".join(qa["actions"]).lower()
        self.assertNotIn("blank", actions)
        self.assertNotIn("font", actions)
        self.assertNotIn("spacing", actions)

    def test_inconsistent_body_page_arithmetic_fails_closed(self) -> None:
        cases = (
            (30, 25, 2, 25),
            (30, 25, 0, 24),
            (30, 25, 7, 31),
            (30, 25, 9, 8),
        )
        for total, body, start, end in cases:
            with self.subTest(case=(total, body, start, end)):
                qa = evaluate_page_gate(
                    total_pages=total,
                    body_pages=body,
                    body_start=start,
                    body_end=end,
                )
                self.assertEqual("fail", qa["status"])
                self.assertTrue(qa["failed_checks"])

    def test_compiled_pdf_uses_aux_labels_for_body_range(self) -> None:
        pdf = self.root / "paper.pdf"
        aux = self.root / "paper.aux"
        write_text_pdf(pdf, 26)
        aux.write_text(
            "\\newlabel{mm-body-start}{{1}{1}}\n"
            "\\newlabel{mm-body-end}{{8}{26}}\n",
            encoding="utf-8",
        )

        with patch("latex_qa.shutil.which", return_value=None):
            report = inspect_pdf(pdf, aux_path=aux, log_paths=[])

        self.assertEqual("pass", report["status"])
        self.assertEqual(26, report["total_pages"])
        self.assertEqual(26, report["body_pages"])
        self.assertEqual({"start": 1, "end": 26, "pages": 26}, report["body_range"])
        self.assertEqual("aux_labels", report["body_range_source"])

    def test_missing_aux_markers_and_unresolved_references_fail(self) -> None:
        pdf = self.root / "paper.pdf"
        aux = self.root / "paper.aux"
        log = self.root / "paper.log"
        write_text_pdf(pdf, 26)
        aux.write_text("\\relax\n", encoding="utf-8")
        log.write_text(
            "LaTeX Warning: There were undefined references.\n",
            encoding="utf-8",
        )

        with patch("latex_qa.shutil.which", return_value=None):
            report = inspect_pdf(pdf, aux_path=aux, log_paths=[log])

        self.assertEqual("fail", report["status"])
        checks = " ".join(report["failed_checks"]).lower()
        self.assertIn("marker", checks)
        self.assertIn("reference", checks)

    def test_page_regex_fragment_is_not_accepted_as_a_pdf(self) -> None:
        pdf = self.root / "fake.pdf"
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n%%EOF\n")
        aux = self.root / "fake.aux"
        aux.write_text(
            "\\newlabel{mm-body-start}{{1}{1}}\n"
            "\\newlabel{mm-body-end}{{8}{1}}\n",
            encoding="utf-8",
        )

        with patch("latex_qa.shutil.which", return_value=None):
            report = inspect_pdf(pdf, aux_path=aux, log_paths=[])

        self.assertEqual("fail", report["status"])
        self.assertIn("PDF", " ".join(report["failed_checks"]))

    def test_trailing_bytes_after_eof_are_rejected(self) -> None:
        pdf = self.root / "trailing.pdf"
        write_text_pdf(pdf, 25)
        pdf.write_bytes(pdf.read_bytes() + b"unexpected trailing payload")
        aux = self.root / "trailing.aux"
        aux.write_text(
            "\\newlabel{mm-body-start}{{1}{1}}\n"
            "\\newlabel{mm-body-end}{{8}{25}}\n",
            encoding="utf-8",
        )

        with patch("latex_qa.shutil.which", return_value=None):
            report = inspect_pdf(pdf, aux_path=aux, log_paths=[])

        self.assertEqual("fail", report["status"])

    def test_valid_xref_stream_pdf_is_not_misclassified_as_broken(self) -> None:
        pdf = self.root / "xref-stream.pdf"
        write_xref_stream_pdf(pdf)
        aux = self.root / "xref-stream.aux"
        aux.write_text(
            "\\newlabel{mm-body-start}{{1}{1}}\n"
            "\\newlabel{mm-body-end}{{8}{1}}\n",
            encoding="utf-8",
        )

        with patch("latex_qa.shutil.which", return_value=None):
            report = inspect_pdf(pdf, aux_path=aux, log_paths=[])

        self.assertEqual("needs_revision", report["status"])
        self.assertEqual([], report["failed_checks"])
        self.assertEqual(1, report["total_pages"])


if __name__ == "__main__":
    unittest.main()
