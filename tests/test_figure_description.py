"""FigureDescriber plug-in point: validation, caching, enrichment, cropping, and its effect on chunks (no real model)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.chunking import ChunkingEngine
from ai.ingestion.figure_description import (
    DescriptionCache,
    FigureContext,
    FigureCrop,
    FigureDescription,
    NullFigureDescriber,
    PdfFigureCropper,
    StubFigureDescriber,
    enrich_figures,
    validate_description,
)
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import Document, FigureData, PageContent
from tests.chunk_fixtures import CTX, SMALL, WordCounter
from tests.test_figures import pdf_with_figure

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def figure(**kw) -> FigureData:
    base = {
        "page_number": 1, "index": 0, "kind": "raster", "bbox": (10.0, 10.0, 200.0, 150.0), "label": "Figure 1", "number": "1",
        "caption": "Figure 1: Validation accuracy of four models, best 93.1 after 40 epochs.", "ocr_text": "ResNet 88.4 ViT 93.1",
    }
    base.update(kw)
    return FigureData(**base)  # type: ignore[arg-type]


def document_with(*figures: FigureData) -> Document:
    page = PageContent(page_number=1, figures=list(figures))
    return Document(source_path="paper.pdf", pages=[page])


class FakeCropper:
    def __init__(self, crop: FigureCrop | None = FigureCrop(PNG, 40, 30)) -> None:
        self.crop_value = crop
        self.calls = 0

    def crop(self, source_path, fig):
        self.calls += 1
        return self.crop_value


class CountingDescriber:
    model_name = "counting"
    prompt_version = "v1"

    def __init__(self, text: str = "The chart compares four models and shows the last one reaching the highest accuracy.", fail: bool = False) -> None:
        self.text, self.fail, self.calls = text, fail, 0

    def describe(self, crop: FigureCrop, context: FigureContext) -> FigureDescription:
        self.calls += 1
        if self.fail:
            raise RuntimeError("model crashed")
        return FigureDescription(text=self.text, figure_type="chart", model=self.model_name, prompt_version=self.prompt_version)


class ValidationTests(unittest.TestCase):
    def test_numbers_from_the_authors_text_are_allowed(self) -> None:
        text = "The curve of the last model peaks at 93.1 while the first stays near 88.4 overall."
        self.assertIsNone(validate_description(FigureDescription(text=text), figure()))

    def test_invented_numbers_are_a_conflict(self) -> None:
        reason = validate_description(FigureDescription(text="The best model reaches 97.5 accuracy on the benchmark overall."), figure())
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("conflict"))
        self.assertIn("97.5", reason)

    def test_numbers_the_model_says_it_read_are_checked_too(self) -> None:
        description = FigureDescription(text="The chart compares several models on the benchmark.", visible_numbers=("12,000",))
        self.assertIn("12000", validate_description(description, figure()) or "")

    def test_small_numbers_in_words_are_not_flagged(self) -> None:
        self.assertIsNone(validate_description(FigureDescription(text="Four lines are drawn and 2 of them cross near the middle."), figure()))

    def test_empty_short_and_boilerplate_descriptions_are_rejected(self) -> None:
        for text in ("", "too short", "This image shows a chart."):
            with self.subTest(text=text):
                self.assertEqual(validate_description(FigureDescription(text=text), figure()), "empty or boilerplate")


class EnrichmentTests(unittest.TestCase):
    def test_description_is_stored_separately_from_the_authors_words(self) -> None:
        fig = figure()
        report = enrich_figures(document_with(fig), CountingDescriber(), FakeCropper())
        self.assertEqual((report.described, report.failed, report.skipped), (1, 0, 0))
        self.assertEqual(fig.description_status, "done")
        self.assertIn("highest accuracy", fig.description)
        self.assertTrue(fig.caption.startswith("Figure 1:"))  # untouched
        self.assertEqual(fig.figure_type, "chart")
        self.assertEqual(len(fig.image_sha256), 64)

    def test_results_are_cached_by_image_model_and_prompt_version(self) -> None:
        cache = DescriptionCache()
        describer = CountingDescriber()
        enrich_figures(document_with(figure()), describer, FakeCropper(), cache=cache)
        again = enrich_figures(document_with(figure()), describer, FakeCropper(), cache=cache)
        self.assertEqual((describer.calls, again.from_cache), (1, 1))

        upgraded = CountingDescriber()
        upgraded.prompt_version = "v2"
        enrich_figures(document_with(figure()), upgraded, FakeCropper(), cache=cache)
        self.assertEqual(upgraded.calls, 1)  # a new prompt version never reuses old answers
        other_image = FakeCropper(FigureCrop(PNG + b"x", 40, 30))
        enrich_figures(document_with(figure()), describer, other_image, cache=cache)
        self.assertEqual(describer.calls, 2)

    def test_cache_survives_restarts_when_given_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            enrich_figures(document_with(figure()), CountingDescriber(), FakeCropper(), cache=DescriptionCache(path))
            describer = CountingDescriber()
            enrich_figures(document_with(figure()), describer, FakeCropper(), cache=DescriptionCache(path))
            self.assertEqual(describer.calls, 0)

    def test_a_corrupt_cache_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(len(DescriptionCache(path)), 0)

    def test_figures_without_a_crop_are_skipped(self) -> None:
        fig = figure(kind="caption_only")
        report = enrich_figures(document_with(fig), CountingDescriber(), FakeCropper(None))
        self.assertEqual((report.skipped, fig.description_status), (1, "skipped"))

    def test_one_failing_figure_does_not_stop_the_rest(self) -> None:
        bad, good = figure(index=0), figure(index=1, label="Figure 2", number="2")
        calls = {"n": 0}

        class Flaky(CountingDescriber):
            def describe(self, crop, context):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("boom")
                return super().describe(crop, context)

        report = enrich_figures(document_with(bad, good), Flaky(), FakeCropper())
        self.assertEqual((report.failed, report.described), (1, 1))
        self.assertEqual((bad.description_status, good.description_status), ("failed", "done"))

    def test_conflicting_descriptions_are_dropped_and_recorded(self) -> None:
        fig = figure()
        report = enrich_figures(document_with(fig), CountingDescriber("Accuracy reaches 99.9 for the best of all models overall."), FakeCropper())
        self.assertEqual((fig.description, fig.description_status), ("", "conflict"))
        self.assertEqual(report.rejected[0][0], "Figure 1")
        self.assertEqual(report.described, 0)

    def test_null_describer_leaves_figures_undescribed(self) -> None:
        fig = figure()
        enrich_figures(document_with(fig), NullFigureDescriber(), FakeCropper())
        self.assertEqual(fig.description, "")
        self.assertNotEqual(fig.description_status, "done")

    def test_done_figures_are_not_redone_unless_asked(self) -> None:
        fig = figure()
        describer = CountingDescriber()
        enrich_figures(document_with(fig), describer, FakeCropper())
        enrich_figures(document_with(fig), describer, FakeCropper())
        self.assertEqual(describer.calls, 1)
        enrich_figures(document_with(fig), describer, FakeCropper(), redo=True)
        self.assertEqual(describer.calls, 2)

    def test_max_figures_bounds_the_work(self) -> None:
        figures = [figure(index=i, label=f"Figure {i}", number=str(i)) for i in range(4)]
        describer = CountingDescriber()
        enrich_figures(document_with(*figures), describer, FakeCropper(), max_figures=2)
        self.assertEqual(describer.calls, 2)

    def test_context_given_to_the_describer_carries_only_the_authors_words(self) -> None:
        seen: list[FigureContext] = []

        class Spy(CountingDescriber):
            def describe(self, crop, context):
                seen.append(context)
                return super().describe(crop, context)

        fig = figure(mentions=["As shown in Figure 1, the last model wins."])
        enrich_figures(document_with(fig), Spy(), FakeCropper())
        self.assertEqual(seen[0].caption, fig.caption)
        self.assertEqual(seen[0].mentions, ("As shown in Figure 1, the last model wins.",))
        self.assertEqual(seen[0].file_name, "paper.pdf")


class PdfCropperAndChunkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pdf_with_figure(Path(self._tmp.name) / "paper.pdf")
        self.document = IngestionPipeline().ingest(self.path)

    def test_crop_of_a_raster_figure_is_a_png_of_its_box(self) -> None:
        crop = PdfFigureCropper(dpi=72).crop(self.path, self.document.pages[0].figures[0])
        self.assertIsNotNone(crop)
        self.assertTrue(crop.png.startswith(b"\x89PNG"))
        self.assertGreater(crop.width, 100)

    def test_no_crop_for_caption_only_figures_missing_boxes_or_unreadable_files(self) -> None:
        cropper = PdfFigureCropper()
        self.assertIsNone(cropper.crop(self.path, figure(kind="caption_only")))
        self.assertIsNone(cropper.crop(self.path, figure(bbox=None)))
        self.assertIsNone(cropper.crop(Path(self._tmp.name) / "missing.pdf", figure()))

    def test_enrichment_changes_only_the_figure_chunk_and_never_renames_the_others(self) -> None:
        engine = ChunkingEngine(SMALL.__class__(), WordCounter())
        before = engine.run(self.document, CTX)
        report = enrich_figures(self.document, StubFigureDescriber("The chart compares four models and one of them clearly leads the others."), PdfFigureCropper(dpi=72))
        after = engine.run(self.document, CTX)

        self.assertEqual(report.described, 1)
        other_before = {c.chunk_id for c in before.children if c.kind != "figure"}
        other_after = {c.chunk_id for c in after.children if c.kind != "figure"}
        self.assertEqual(other_before, other_after)  # E2E-08: untouched chunks keep their ids
        figure_before = next(c for c in before.children if c.kind == "figure")
        figure_after = next(c for c in after.children if c.kind == "figure")
        self.assertNotEqual(figure_before.chunk_id, figure_after.chunk_id)
        self.assertIn("Generated description (AI-generated, may contain errors)", figure_after.text)
        self.assertNotIn("Generated description", figure_before.text)
        self.assertIn("Accuracy of four models", figure_after.text)  # the author's caption is still there
        self.assertEqual(after.report.problems, [])


if __name__ == "__main__":
    unittest.main()
