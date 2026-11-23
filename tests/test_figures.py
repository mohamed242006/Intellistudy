"""Phase 0 figure infrastructure: captions, detection, selection, linking, chunking, citations (no VLM)."""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw
from pptx.util import Inches, Pt

from ai.chunking import ChunkingEngine
from ai.ingestion.figure_selection import (
    SelectionConfig,
    model_probability,
    select_figures,
)
from ai.ingestion.figures import guess_figure_type, link_mentions, parse_caption
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import Block, BlockType, FigureData, ImageData, PageContent
from ai.ingestion.pptx_reader import PptxReader
from tests import pptx_fixtures as fx
from tests.chunk_fixtures import CTX, SMALL, H, Pg, WordCounter, build


def chart_png(size: tuple[int, int] = (480, 300)) -> bytes:
    """A flat-colour bar chart with axis labels: what a plot looks like to the selector."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.line((40, 20, 40, size[1] - 40), fill="black", width=2)
    draw.line((40, size[1] - 40, size[0] - 20, size[1] - 40), fill="black", width=2)
    for i, height in enumerate((60, 120, 90, 160)):
        x = 70 + i * 90
        draw.rectangle((x, size[1] - 40 - height, x + 50, size[1] - 41), fill=(30, 90, 200))
        draw.text((x + 8, size[1] - 32), f"M{i + 1}", fill="black")
    draw.text((8, 8), "Accuracy 0.62 0.81 0.74 0.93", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def logo_png() -> bytes:
    image = Image.new("RGB", (120, 80), (200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class CaptionParsingTests(unittest.TestCase):
    def test_captions_with_punctuation_are_recognised_and_normalised(self) -> None:
        cases = {
            "Figure 3: Accuracy of each model": ("Figure 3", "3"),
            "Fig. 2. The processing pipeline": ("Figure 2", "2"),
            "FIG. 4: Absolute value of the bispectrum": ("Figure 4", "4"),
            "Figure 5 – Layered architecture": ("Figure 5", "5"),
            "Fig 6) System overview": ("Figure 6", "6"),
            "Figure 2b: Right panel": ("Figure 2b", "2b"),
            "Chart 1: Revenue by quarter": ("Chart 1", "1"),
        }
        for text, (label, number) in cases.items():
            with self.subTest(text=text):
                caption = parse_caption(text)
                self.assertIsNotNone(caption)
                self.assertEqual((caption.label, caption.number), (label, number))

    def test_sentences_and_other_things_are_not_captions(self) -> None:
        for text in (
            "Figure 3 shows that the model converges quickly.",
            "Figure 3",
            "Table 2: Results by model",
            "As described in Figure 3: the model works",
            "The figure below illustrates the idea.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_caption(text))

    def test_a_bold_label_marks_a_caption_even_without_punctuation(self) -> None:
        self.assertIsNone(parse_caption("Figure 3 Accuracy of each model"))
        self.assertIsNotNone(parse_caption("Figure 3 Accuracy of each model", bold_label=True))

    def test_figure_type_guess_uses_caption_words(self) -> None:
        self.assertEqual(guess_figure_type("Validation accuracy versus epochs"), "chart")
        self.assertEqual(guess_figure_type("Architecture of the proposed framework"), "diagram")
        self.assertEqual(guess_figure_type("Photo of the specimen"), "photo")
        self.assertEqual(guess_figure_type("Something unrelated"), "unknown")


class MentionLinkingTests(unittest.TestCase):
    @staticmethod
    def doc_with(figures_by_page: dict[int, list[FigureData]], paragraphs: dict[int, list[str]]):
        from ai.ingestion.models import Document

        pages = []
        for number in sorted(set(figures_by_page) | set(paragraphs)):
            page = PageContent(page_number=number, figures=figures_by_page.get(number, []))
            page.blocks = [Block(BlockType.PARAGRAPH, text, number) for text in paragraphs.get(number, [])]
            pages.append(page)
        document = Document(source_path="x", pages=pages)
        for order, block in enumerate(document.blocks):
            block.order = order
        return document

    def test_citing_sentences_are_linked_and_whitespace_collapsed(self) -> None:
        figure = FigureData(page_number=2, index=0, kind="raster", label="Figure 3", number="3", caption="Figure 3: Accuracy")
        document = self.doc_with(
            {2: [figure]},
            {1: ["Intro text. As shown in Figure 3, model B\nwins clearly. Other sentence."], 3: ["See also Fig. 3 for details."]},
        )
        self.assertEqual(link_mentions(document), 2)
        self.assertEqual(figure.mentions[0], "As shown in Figure 3, model B wins clearly.")
        self.assertEqual(len(figure.referenced_by), 2)

    def test_mention_must_match_the_whole_number(self) -> None:
        figure = FigureData(page_number=1, index=0, kind="raster", label="Figure 1", number="1", caption="Figure 1: x")
        document = self.doc_with({1: [figure]}, {1: ["Figure 12 is different.", "Figure 1a is a panel.", "Figure 1 is this one."]})
        link_mentions(document)
        self.assertEqual(figure.mentions, ["Figure 1 is this one."])

    def test_a_repeated_label_is_matched_only_near_its_page(self) -> None:
        first = FigureData(page_number=1, index=0, kind="raster", label="Figure 1", number="1", caption="Figure 1: a")
        second = FigureData(page_number=9, index=0, kind="raster", label="Figure 1", number="1", caption="Figure 1: b")
        document = self.doc_with({1: [first], 9: [second]}, {2: ["Figure 1 here."], 9: ["Figure 1 there."]})
        link_mentions(document)
        self.assertEqual(first.mentions, ["Figure 1 here."])
        self.assertEqual(second.mentions, ["Figure 1 there."])

    def test_a_figures_own_caption_paragraph_is_not_a_mention(self) -> None:
        figure = FigureData(page_number=1, index=0, kind="raster", label="Figure 1", number="1", caption="Figure 1: Accuracy")
        document = self.doc_with({1: [figure]}, {1: ["Figure 1: Accuracy"]})
        self.assertEqual(link_mentions(document), 0)

    def test_at_most_two_mentions_are_kept(self) -> None:
        figure = FigureData(page_number=1, index=0, kind="raster", label="Figure 1", number="1", caption="Figure 1: x")
        document = self.doc_with({1: [figure]}, {1: [f"Para {i} cites Figure 1." for i in range(5)]})
        link_mentions(document)
        self.assertEqual(len(figure.mentions), 2)
        self.assertEqual(len(figure.referenced_by), 5)  # every citing block is still recorded


def candidate(
    *, kind: str = "raster", bbox=(100.0, 200.0, 400.0, 450.0), caption: str = "", number: str = "", image: ImageData | None = None, text: str = ""
):
    page = PageContent(page_number=1, size=(612.0, 792.0))
    if image is not None:
        page.images.append(image)
    figure = FigureData(
        page_number=1, index=0, kind=kind, bbox=bbox, caption=caption, number=number,
        label=f"Figure {number}" if number else "", image_index=0 if image is not None else None, inner_text=text,
    )
    page.figures.append(figure)
    return page, figure


def picture(width: int = 800, height: int = 500, **stats) -> ImageData:
    defaults = {"dominant_fraction": 0.8, "white_fraction": 0.7, "edge_density": 0.1, "distinct_colors": 8}
    defaults.update(stats)
    return ImageData(page_number=1, index=0, xref=0, width=width, height=height, **defaults)


class SelectionRuleTests(unittest.TestCase):
    def decide(self, pages: list[PageContent]):
        return [(f, d) for f, d in select_figures(pages, SelectionConfig())]

    def test_tiny_pictures_and_banners_are_rejected_even_with_a_caption(self) -> None:
        page, _ = candidate(caption="Figure 1: x", number="1", image=picture(width=40, height=40))
        self.assertIn("tiny picture", self.decide([page])[0][1].reasons[0])
        page, _ = candidate(bbox=(0.0, 100.0, 600.0, 112.0), image=picture())
        self.assertIn("tiny on the page", self.decide([page])[0][1].reasons[0])
        page, _ = candidate(bbox=(0.0, 100.0, 600.0, 160.0), image=picture())
        self.assertIn("banner", self.decide([page])[0][1].reasons[0])

    def test_a_caption_keeps_a_figure(self) -> None:
        page, _ = candidate(caption="Figure 2: Pipeline", number="2", image=picture(dominant_fraction=0.2, white_fraction=0.0))
        decision = self.decide([page])[0][1]
        self.assertTrue(decision.keep)
        self.assertIn("caption", decision.reasons[0])

    def test_a_caption_without_graphic_is_kept_because_the_words_are_worth_keeping(self) -> None:
        page, _ = candidate(kind="caption_only", caption="Figure 1: Layered architecture", number="1")
        decision = self.decide([page])[0][1]
        self.assertTrue(decision.keep)
        self.assertIn("without a detected graphic", " ".join(decision.reasons))

    def test_small_picture_repeated_on_many_pages_is_template_furniture(self) -> None:
        pages = []
        for number in (1, 2, 3):
            page = PageContent(page_number=number, size=(612.0, 792.0))
            page.images.append(ImageData(page_number=number, index=0, xref=7, width=300, height=300, dominant_fraction=0.7, white_fraction=0.5, edge_density=0.1, distinct_colors=9))
            page.figures.append(FigureData(page_number=number, index=0, kind="raster", bbox=(50.0, 50.0, 120.0, 120.0), image_index=0))
            pages.append(page)
        self.assertTrue(all(not d.keep and "several pages" in d.reasons[0] for _, d in self.decide(pages)))

    def test_large_picture_repeated_on_slide_builds_keeps_only_the_first(self) -> None:
        pages = []
        for number in (1, 2, 3, 4):
            page = PageContent(page_number=number, size=(960.0, 540.0))
            page.images.append(ImageData(page_number=number, index=0, xref=0, width=2000, height=1500, thumb_hash="abc", dominant_fraction=0.9, white_fraction=0.8, edge_density=0.2, distinct_colors=6))
            page.figures.append(FigureData(page_number=number, index=0, kind="pptx_picture", bbox=(100.0, 80.0, 800.0, 480.0), image_index=0, inner_text="Firewall Gateway Server Client 10 20"))
            pages.append(page)
        verdicts = [d.keep for _, d in self.decide(pages)]
        self.assertEqual(verdicts, [True, False, False, False])

    def test_citation_in_the_text_raises_an_uncaptioned_figure_over_the_threshold(self) -> None:
        pages = [PageContent(page_number=1, size=(612.0, 792.0), text="")]
        figure = FigureData(page_number=1, index=0, kind="raster", bbox=(100.0, 200.0, 300.0, 330.0), number="4", label="Figure 4", image_index=0)
        pages[0].images.append(picture(width=300, height=200, dominant_fraction=0.3, white_fraction=0.0, edge_density=0.05, distinct_colors=80))
        pages[0].figures.append(figure)
        without = select_figures(pages, SelectionConfig())[0][1]
        pages[0].text = "The curve in Figure 4 rises sharply."
        with_citation = select_figures(pages, SelectionConfig())[0][1]
        self.assertGreater(with_citation.score, without.score)
        self.assertIn("cited in the text", with_citation.reasons)

    def test_the_budget_keeps_the_highest_scoring_figures(self) -> None:
        page = PageContent(page_number=1, size=(612.0, 792.0))
        for index in range(5):
            page.images.append(picture())
            page.figures.append(
                FigureData(page_number=1, index=index, kind="raster", bbox=(50.0, 50.0 + index * 120, 350.0, 150.0 + index * 120), caption=f"Figure {index}: x", number=str(index), image_index=index)
            )
        decided = select_figures([page], SelectionConfig(max_per_document=2))
        self.assertEqual(sum(d.keep for _, d in decided), 2)
        self.assertTrue(any("budget" in " ".join(d.reasons) for _, d in decided))

    def test_model_prefers_a_wordy_flat_diagram_over_a_colourful_photo(self) -> None:
        diagram = {"area": 0.3, "aspect": 1.6, "colors": 10.0, "dominant": 0.85, "white": 0.8, "edge": 0.15, "ocr_words": 12.0, "numbers": 3.0}
        photo = {"area": 0.3, "aspect": 1.5, "colors": 120.0, "dominant": 0.15, "white": 0.0, "edge": 0.1, "ocr_words": 0.0, "numbers": 0.0}
        self.assertGreater(model_probability(diagram), model_probability(photo) + 0.3)


def pdf_with_figure(path: Path, *, with_logo: bool = True, mention: bool = True, vector: bool = False) -> Path:
    """Three pages: a body paragraph citing Figure 1, the figure with its caption underneath, and (optionally) a logo."""
    document = fitz.open()
    for number in (1, 2, 3):
        page = document.new_page()
        page.insert_text((72, 72), f"Section {number}", fontsize=16)
        body = "We evaluate four models on the benchmark. " + ("As shown in Figure 1, model M4 reaches the highest accuracy. " if mention and number == 1 else "")
        page.insert_textbox(fitz.Rect(72, 100, 540, 180), body * 2, fontsize=11)
        if number == 1:
            if vector:
                for i, height in enumerate((50, 110, 80, 150)):
                    x = 120 + i * 80
                    page.draw_rect(fitz.Rect(x, 420 - height, x + 40, 420), fill=(0.1, 0.35, 0.8))
                    page.insert_text((x + 6, 436), f"M{i + 1}", fontsize=9)
                page.draw_line((100, 260), (100, 420))
                page.draw_line((100, 420), (460, 420))
                for g in range(8):
                    page.draw_line((100, 280 + g * 17), (460, 280 + g * 17), color=(0.8, 0.8, 0.8))
            else:
                page.insert_image(fitz.Rect(100, 240, 460, 465), stream=chart_png())
            page.insert_text((100, 485), "Figure 1: Accuracy of four models on the benchmark.", fontsize=10)
        if with_logo:
            page.insert_image(fitz.Rect(500, 30, 560, 70), stream=logo_png())
    document.save(str(path))
    document.close()
    return path


class PdfFigureTests(unittest.TestCase):
    def ingest(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            return IngestionPipeline().ingest(pdf_with_figure(Path(tmp) / "paper.pdf", **kwargs))

    def test_raster_figure_with_caption_becomes_one_figure_block(self) -> None:
        document = self.ingest()
        figures = [b for b in document.blocks if b.type == BlockType.FIGURE]
        self.assertEqual(len(figures), 1)
        figure = document.pages[0].figures[0]
        self.assertEqual((figure.label, figure.kind), ("Figure 1", "raster"))
        self.assertTrue(figure.caption.startswith("Figure 1: Accuracy of four models"))
        self.assertEqual(document.statistics["figure_count"], 1)

    def test_caption_is_taken_out_of_the_running_text(self) -> None:
        document = self.ingest()
        paragraphs = [b.text for b in document.blocks if b.type == BlockType.PARAGRAPH]
        self.assertFalse(any(p.startswith("Figure 1:") for p in paragraphs))

    def test_the_logo_repeated_on_every_page_is_not_a_figure(self) -> None:
        document = self.ingest()
        self.assertEqual(sum(len(p.figures) for p in document.pages), 1)
        skipped = document.metadata["figures"]["skipped"]
        self.assertTrue(any("template" in " ".join(s["reasons"]) or "tiny" in " ".join(s["reasons"]) for s in skipped))

    def test_citing_sentence_is_linked_to_the_figure(self) -> None:
        document = self.ingest()
        figure = document.pages[0].figures[0]
        self.assertTrue(any("model M4 reaches the highest accuracy" in m for m in figure.mentions))
        self.assertTrue(figure.referenced_by)

    def test_vector_chart_is_detected_and_its_labels_move_into_the_figure(self) -> None:
        document = self.ingest(with_logo=False, vector=True)
        figure = document.pages[0].figures[0]
        self.assertEqual(figure.kind, "vector_region")
        self.assertIn("M1", figure.inner_text)
        paragraphs = " ".join(b.text for b in document.blocks if b.type == BlockType.PARAGRAPH)
        self.assertNotIn("M1 M2", paragraphs)

    def test_a_sentence_starting_with_figure_is_not_mistaken_for_a_caption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_textbox(fitz.Rect(72, 72, 540, 200), "Figure 3 shows that the model converges quickly on every benchmark we tried.", fontsize=11)
            document.save(str(path))
            document.close()
            result = IngestionPipeline().ingest(path)
        self.assertEqual(sum(len(p.figures) for p in result.pages), 0)
        self.assertTrue(any("Figure 3 shows" in b.text for b in result.blocks))

    def test_figures_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = IngestionPipeline(enable_figures=False).ingest(pdf_with_figure(Path(tmp) / "paper.pdf"))
        self.assertEqual(document.statistics["figure_count"], 0)
        self.assertTrue(any(b.text.startswith("Figure 1:") for b in document.blocks if b.type == BlockType.PARAGRAPH))


class FigureChunkTests(unittest.TestCase):
    def chunks(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            document = IngestionPipeline().ingest(pdf_with_figure(Path(tmp) / "paper.pdf", **kwargs))
        return document, ChunkingEngine(SMALL.__class__(), WordCounter()).run(document, CTX)

    def test_figure_chunk_is_isolated_cited_and_carries_figure_metadata(self) -> None:
        _document, chunk_set = self.chunks()
        figures = [c for c in chunk_set.children if c.kind == "figure"]
        self.assertEqual(len(figures), 1)
        chunk = figures[0]
        self.assertTrue(chunk.citation_label.endswith("Figure 1"))
        self.assertTrue(chunk.citation_label.startswith("p. 1"))
        self.assertEqual((chunk.figure_label, chunk.figure_kind), ("Figure 1", "raster"))
        self.assertEqual(chunk.block_types, ("figure",))
        self.assertEqual(chunk_set.report.problems, [])
        meta = chunk.chroma_metadata()
        self.assertEqual((meta["kind"], meta["figure_label"], meta["figure_kind"]), ("figure", "Figure 1", "raster"))
        self.assertTrue(meta["figure_id"].endswith("-F1.0"))

    def test_figure_chunk_text_uses_the_fixed_template_with_source_text_only(self) -> None:
        _document, chunk_set = self.chunks()
        text = next(c.text for c in chunk_set.children if c.kind == "figure")
        self.assertTrue(text.startswith("[Figure 1] (page 1)"))
        self.assertIn("Accuracy of four models", text)
        self.assertIn('Discussed in text: "As shown in Figure 1', text)
        self.assertNotIn("Generated description", text)  # Phase 0 never invents text

    def test_non_figure_chunks_have_no_figure_metadata(self) -> None:
        _document, chunk_set = self.chunks()
        text_chunk = next(c for c in chunk_set.children if c.kind == "text")
        self.assertNotIn("figure_id", text_chunk.chroma_metadata())

    def test_oversize_caption_and_text_are_clipped_to_fit_one_chunk(self) -> None:
        figure = FigureData(
            page_number=1, index=0, kind="raster", bbox=(0.0, 0.0, 10.0, 10.0), label="Figure 1", number="1",
            caption="Figure 1: " + "very long caption " * 400, inner_text="axis label " * 600,
            mentions=["cites " * 300, "again " * 300],
        )
        page = PageContent(page_number=1, figures=[figure])
        blocks = [H("A"), Pg("Some intro words here."), Block(BlockType.FIGURE, "x", 1, ref_index=0)]
        document = build(blocks, pages=[page])
        chunk_set = ChunkingEngine(SMALL, WordCounter()).run(document, CTX)
        chunk = next(c for c in chunk_set.children if c.kind == "figure")
        self.assertLessEqual(chunk.token_count, SMALL.max_tokens)
        self.assertEqual(chunk_set.report.problems, [])
        self.assertTrue(chunk.text.rstrip().endswith("..."))

    def test_figure_chunk_is_never_merged_with_its_neighbours(self) -> None:
        _document, chunk_set = self.chunks()
        for chunk in chunk_set.children:
            if chunk.kind == "figure":
                self.assertEqual(set(chunk.block_types), {"figure"})
        self.assertGreater(len(chunk_set.children), 1)


class PptxFigureTests(unittest.TestCase):
    def deck(self, directory: Path, *, caption: bool = True) -> Path:
        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        title = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(8), Inches(0.8))
        title.text_frame.text = "Model comparison"
        title.text_frame.paragraphs[0].runs[0].font.size = Pt(32)
        picture_path = directory / "chart.png"
        picture_path.write_bytes(chart_png((960, 600)))
        pic = slide.shapes.add_picture(str(picture_path), Inches(1.5), Inches(1.4), Inches(5.5), Inches(3.4))
        pic._element.xpath("./p:nvPicPr/p:cNvPr")[0].set("descr", "Bar chart comparing four models")
        if caption:
            box = slide.shapes.add_textbox(Inches(1.5), Inches(4.9), Inches(5.5), Inches(0.5))
            box.text_frame.text = "Figure 1: Accuracy of four models"
        return fx.save(prs, directory)

    def read(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            return PptxReader(ocr_processor=fx.FakeOCR()).read(self.deck(Path(tmp), **kwargs))  # type: ignore[arg-type]

    def test_picture_with_caption_text_box_becomes_a_figure_block(self) -> None:
        document = self.read()
        figures = [b for b in document.blocks if b.type == BlockType.FIGURE]
        self.assertEqual(len(figures), 1)
        self.assertIn("Accuracy of four models", figures[0].text)
        self.assertEqual(document.pages[0].figures[0].label, "Figure 1")

    def test_caption_text_box_is_not_left_behind_as_a_paragraph(self) -> None:
        document = self.read()
        self.assertFalse(any(b.type == BlockType.PARAGRAPH and b.text.startswith("Figure 1") for b in document.blocks))

    def test_alt_text_is_recorded_and_used_when_there_is_no_caption(self) -> None:
        document = self.read(caption=False)
        figure = document.pages[0].figures[0] if document.pages[0].figures else None
        self.assertIsNotNone(figure)
        self.assertEqual(figure.alt_text, "Bar chart comparing four models")
        self.assertTrue(any(b.type == BlockType.FIGURE and "Bar chart comparing four models" in b.text for b in document.blocks))

    def test_chart_values_are_extracted_as_data_lines(self) -> None:
        prs = fx.blank_presentation()
        fx.add_chart_slide(prs)
        with tempfile.TemporaryDirectory() as tmp:
            document = PptxReader(ocr_processor=fx.FakeOCR()).read(fx.save(prs, Path(tmp)))  # type: ignore[arg-type]
        chart = next(b.text for b in document.blocks if b.type == BlockType.CHART)
        self.assertIn("Data:", chart)


class DocxFigureTests(unittest.TestCase):
    def read(self, build_document):
        import docx

        from ai.ingestion.docs_reader import DocxReader

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.docx"
            document = docx.Document()
            build_document(document, Path(tmp))
            document.save(str(path))
            return DocxReader(ocr_processor=fx.FakeOCR()).read(path)  # type: ignore[arg-type]

    def test_picture_followed_by_a_caption_paragraph_becomes_one_figure_block(self) -> None:
        def build(document, directory: Path) -> None:
            document.add_heading("Results", level=1)
            document.add_paragraph("The comparison is summarised in Figure 1 below.")
            image_path = directory / "chart.png"
            image_path.write_bytes(chart_png((960, 600)))
            document.add_picture(str(image_path), width=Inches(5.5))
            document.add_paragraph("Figure 1: Accuracy of four models on the benchmark.")

        result = self.read(build)
        figures = [b for b in result.blocks if b.type == BlockType.FIGURE]
        self.assertEqual(len(figures), 1)
        self.assertIn("Accuracy of four models", figures[0].text)
        self.assertFalse(any(b.type == BlockType.PARAGRAPH and b.text.startswith("Figure 1:") for b in result.blocks))
        self.assertEqual(result.pages[0].figures[0].mentions, ["The comparison is summarised in Figure 1 below."])
        self.assertEqual(figures[0].heading_path, ("Results",))

    def test_a_tiny_picture_is_not_a_figure(self) -> None:
        def build(document, directory: Path) -> None:
            document.add_paragraph("Text before the icon.")
            image_path = directory / "icon.png"
            image_path.write_bytes(logo_png())
            document.add_picture(str(image_path), width=Inches(0.2))

        result = self.read(build)
        self.assertEqual(result.statistics["figure_count"], 0)


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
class SyntheticPaperRegressionTests(unittest.TestCase):
    """A matplotlib chart embedded as vector graphics: pdfplumber reads its gridlines and legend as a table."""

    def test_raster_and_vector_charts_are_both_found_and_no_phantom_table_remains(self) -> None:
        from evaluation.figure_benchmark.synthetic import build

        with tempfile.TemporaryDirectory() as tmp:
            truth = build(Path(tmp), limit=1)
            document = IngestionPipeline().ingest(Path(tmp) / truth["papers"][0]["file"])

        figures = [f for page in document.pages for f in page.figures]
        self.assertEqual([(f.label, f.kind) for f in figures], [("Figure 1", "raster"), ("Figure 2", "vector_region")])
        self.assertTrue(all(f.mentions for f in figures))
        self.assertIn("ResNet-50", figures[1].inner_text)  # legend text of the vector chart
        self.assertEqual(document.statistics["table_count"], 0)
        self.assertEqual(sum(1 for b in document.blocks if b.type == BlockType.FIGURE), 2)


if __name__ == "__main__":
    unittest.main()
