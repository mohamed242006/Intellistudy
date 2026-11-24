"""M4.1 regressions from the manual DeepSeek run on a real journal PDF (docs/project_context.md, M4.1).

F-M4-06: the PDF's font maps its hyphenation glyph to a soft hyphen (U+00AD), so the extracted text keeps every
line-end word split ("adher\\u00ad\\nence"). A model quoting the word as printed ("adherence") failed the verbatim
evidence check: 10 of 22 generated questions were dropped for it. The SOURCE strings below are verbatim extractions
from that PDF (an open-access article); the quotes are the ones DeepSeek returned.

F-M4-05: the sentence splitter broke "the U.S. (26.8%)" and "Syst Rev. 2021;10(1):89" in two; grounding removed the
first half and kept an orphaned fragment that was shown to the student.
"""

from __future__ import annotations

import unittest
from typing import Any

from ai.answering import citations
from ai.answering.llm import ScriptedLLM
from ai.answering.models import ContextBundle
from backend.app.services import quizgen, summaries
from backend.app.services.sources import Section

SHY = "­"

# Verbatim extracted text (page 7 and page 5 of the run's PDF), including its soft-hyphen and bare line breaks.
SOURCE_ADHERENCE = (
    "guidelines illustrated in a bar chart. The overall mean\nadherence across all studies was 34.07% (SD: 11.15).\n"
    f"Studies using conventional statistical models had a higher\nmean adherence to TRIPOD (38.11%, SD:10.39) com{SHY}\n"
    "pared to studies employing machine learning approaches,\nwhich showed lower adherence to TRIPOD + AI (28.37%,\n"
    "SD: 8.91; p = 0.0012)."
)
SOURCE_MODELS = (
    f"Most models (71.8%) were based on sin{SHY}\ngle-country data, with China (50.7%) and the U.S. (26.8%)\n"
    f"being the most common sources The models predomi{SHY}\nnantly focused on hospitalized patients (87.3%) with con{SHY}\n"
    "firmed COVID-19 (94.4%)."
)

# (source excerpt as extracted, the quote the model returned) - one per evidence drop observed in the run.
OBSERVED = [
    (f"Framework (OSF), accessi{SHY}\nble at https://osf.io/kg9yw.", "Framework (OSF), accessible at https://osf.io/kg9yw."),
    (f"Reviews, and Epis{SHY}\ntemonikos (epistemonikos.org), covering", "Reviews, and Epistemonikos (epistemonikos.org)"),
    (f"poor with average adher{SHY}\nence being below 35%.", "poor with average adherence being below 35%."),
    (f"multivariable predic{SHY}\ntion model for Individual", "multivariable prediction model for Individual"),
    (f"traditional regres{SHY}\nsion techniques (e.g., logistic", "traditional regression techniques (e.g., logistic"),
    (f"failing to report on perfor{SHY}\nmance variability", "failing to report on performance variability"),
    (f"substantially better in TRI{SHY}\nPOD studies (90.3%)", "substantially better in TRIPOD studies (90.3%)"),
    (f"meeting TRIPOD mini{SHY}\nmums and a mere 4.6%", f"meeting TRIPOD mini{SHY}mums and a mere 4.6%"),
    (f"journals that explicitly rec{SHY}\nommended TRIPOD, and", f"journals that explicitly rec{SHY}ommended TRIPOD, and"),
    ("the integration of TRIP\nOD + AI, which addresses", f"the integration of TRIP{SHY}OD + AI, which addresses"),
]


def section(text: str, key: str = "d1:p7", page: int = 7, heading: str = "Results") -> Section:
    return Section(key=key, document_id="d1", file_name="paper.pdf", citation_label=f"p. {page}", page=page, slide=None,
                   heading=heading, text=text, tokens=len(text) // 4)


def mcq(evidence: str, options: list[str], correct: int = 0) -> dict[str, Any]:
    return {"type": "mcq", "stem": "What does the review report about adherence?", "options": options,
            "correct_index": correct, "rationales": [], "sources": ["S1"], "evidence": evidence,
            "topic": "Adherence", "difficulty": "medium", "cognitive_level": "remember"}


def tf(evidence: str, stem: str) -> dict[str, Any]:
    return {"type": "true_false", "stem": stem, "answer": True, "rationale": "Stated.", "sources": ["S1"],
            "evidence": evidence, "topic": "Adherence", "difficulty": "easy", "cognitive_level": "remember"}


OPTIONS = ["higher mean adherence to TRIPOD", "a lower response rate in clinics", "no difference between registries",
           "an increase in sample sizes"]
QUOTE = ("Studies using conventional statistical models had a higher mean adherence to TRIPOD (38.11%, SD:10.39) "
         "compared to studies employing machine learning approaches")


class EvidenceAcrossLineBreakSplitsTest(unittest.TestCase):
    """F-M4-06: a quote that rejoins a word the PDF split at a line end still counts as copied."""

    def check(self, item: dict[str, Any], text: str = SOURCE_ADHERENCE) -> str:
        candidate, reason = quizgen.validate(item, {"S1": section(text)}, ("mcq", "true_false"))
        return "ok" if candidate is not None else reason

    def test_quote_rejoining_a_soft_hyphen_split_is_accepted(self) -> None:
        self.assertEqual(self.check(mcq(QUOTE, OPTIONS)), "ok")

    def test_every_split_observed_in_the_run_is_accepted(self) -> None:
        for text, quote in OBSERVED:
            with self.subTest(quote=quote):
                self.assertTrue(quizgen._quoted(quote, text))

    def test_bare_line_break_splits_are_accepted(self) -> None:
        for text, quote in [("the meth\nodology of the review", "the methodology of the review"),
                            ("the inclu\nsion criteria were", "the inclusion criteria were"),
                            ("all compo\nnents were present", "all components were present")]:
            with self.subTest(quote=quote):
                self.assertTrue(quizgen._quoted(quote, text))

    def test_an_ordinary_line_break_between_words_still_matches_as_a_space(self) -> None:
        self.assertTrue(quizgen._quoted("The overall mean adherence across all studies", SOURCE_ADHERENCE))

    def test_soft_hyphens_are_removed_from_stored_model_text(self) -> None:
        candidate, _ = quizgen.validate(mcq(f"higher mean adher{SHY}ence to TRIPOD (38.11%", OPTIONS),
                                        {"S1": section(SOURCE_ADHERENCE)}, ("mcq",))
        assert candidate is not None
        self.assertNotIn(SHY, candidate.evidence)
        self.assertIn("adherence", candidate.evidence)


class EvidenceStaysStrictTest(unittest.TestCase):
    """The repair adds exactly one freedom (a split word may be read whole); nothing else is relaxed."""

    def test_invented_or_altered_quotes_are_rejected(self) -> None:
        for quote in ["The overall mean adherence across all studies was 43.07%",  # changed number
                      "Studies using conventional models had a higher mean adherence",  # word left out
                      "lower adherence to TRIPOD + AI (28.37%, SD: 8.91; p = 0.001)",  # truncated number
                      "studies employing deep learning approaches"]:  # changed word
            with self.subTest(quote=quote):
                self.assertFalse(quizgen._quoted(quote, SOURCE_ADHERENCE))

    def test_words_cannot_be_joined_where_the_source_has_a_space(self) -> None:
        self.assertFalse(quizgen._quoted("theoverall mean adherence", SOURCE_ADHERENCE))

    def test_a_split_word_cannot_be_read_as_two_words(self) -> None:
        self.assertFalse(quizgen._quoted("TRIPOD (38.11%, SD:10.39) com pared to studies", SOURCE_ADHERENCE))
        self.assertFalse(quizgen._quoted("techniques use pre sent data", f"techniques use pre{SHY}\nsent data"))

    def test_text_cannot_be_skipped_at_a_line_break(self) -> None:
        self.assertFalse(quizgen._quoted("the methology of the review", "the meth\nodology of the review"))
        self.assertFalse(quizgen._quoted("higher adherence to TRIPOD", SOURCE_ADHERENCE))

    def test_a_quote_must_come_from_one_cited_source(self) -> None:
        candidate, reason = quizgen.validate(mcq(QUOTE, OPTIONS), {"S1": section(SOURCE_MODELS)}, ("mcq",))
        self.assertIsNone(candidate)
        self.assertEqual(reason, "evidence")

    def test_answer_checks_still_apply_after_a_rejoined_quote(self) -> None:
        unsupported = ["a decline in registrations", *OPTIONS[1:]]
        self.assertEqual(quizgen.validate(mcq(QUOTE, unsupported), {"S1": section(SOURCE_ADHERENCE)}, ("mcq",))[1],
                         "unsupported_answer")
        doubled = [OPTIONS[0], "machine learning approaches", *OPTIONS[2:]]
        self.assertEqual(quizgen.validate(mcq(QUOTE, doubled), {"S1": section(SOURCE_ADHERENCE)}, ("mcq",))[1],
                         "second_correct_option")
        self.assertEqual(quizgen.validate(tf(QUOTE, "Ethics boards approved every registry protocol."),
                                          {"S1": section(SOURCE_ADHERENCE)}, ("true_false",))[1], "unsupported_answer")


class AbbreviationSplittingTest(unittest.TestCase):
    """F-M4-05: common abbreviations do not end a sentence."""

    def parse(self, text: str) -> list[str]:
        bundle = ContextBundle(question="q", sources=(section(SOURCE_MODELS).source("S1"),), tokens=10)
        return [s.text for s in citations.parse(text, bundle).sentences]

    def test_abbreviations_keep_the_sentence_whole(self) -> None:
        for text in ["China (50.7%) and the U.S. (26.8%) were the most common sources [S1].",
                     "Patients in the U.K. (8.5%) were fewer [S1].",
                     "The PRISMA statement appeared in Syst Rev. 2021;10(1):89 [S1].",
                     "Dr. Partheniadis extracted the data [S1].",
                     "Prof. Haidich supervised the work [S1].",
                     "Predictors included age, sex, etc. (see Table 2) [S1].",
                     "Results appear in Vol. 13 of the journal [S1].",
                     "The search covered MEDLINE, e.g. (via Ovid), and Scopus [S1]."]:
            with self.subTest(text=text):
                self.assertEqual(len(self.parse(text)), 1, self.parse(text))

    def test_real_sentence_ends_still_split(self) -> None:
        self.assertEqual(len(self.parse("Dr. Smith wrote it [S1]. The end came later [S1].")), 2)
        self.assertEqual(len(self.parse("Most were retrospective [S1]. 53 studies met the criteria [S1].")), 2)


class SummaryFragmentsTest(unittest.TestCase):
    """F-M4-05 end to end: the reply shapes from the run no longer leave orphaned fragments in a summary."""

    def summarize(self, reply: str) -> list[str]:
        sections = [section(SOURCE_MODELS, key="d1:p5", page=5),
                    section("14. Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an updated "
                            "guideline for reporting systematic reviews. Syst Rev. 2021;10(1):89.", key="d1:p11",
                            page=11, heading="References")]
        result = summaries.summarize(sections, ScriptedLLM([reply]), batch_tokens=10_000, max_tokens=500)
        return [s["text"] for s in result.sections]

    def test_no_orphaned_fragment_survives(self) -> None:
        texts = " ".join(self.summarize(
            "### [S1]\nThe models predominantly focused on hospitalized patients (87.3%) with confirmed COVID-19 "
            "(94.4%) [S1]. Most models were based on single-country data, with China (50.7%) and the U.S. (26.8%) "
            "the most common sources [S1].\n\n### [S2]\nThe PRISMA 2020 statement is an updated guideline for "
            "reporting systematic reviews [S2]. It appeared in Syst Rev. 2021;10(1):89 [S2]."))
        self.assertIn("hospitalized patients (87.3%)", texts)
        self.assertIn("PRISMA 2020 statement", texts)
        self.assertNotRegex(texts, r"(?:^|\]\.?\s)\(26\.8%\)")
        self.assertNotRegex(texts, r"(?:^|\]\.?\s)2021;10\(1\):89")

    def test_a_citation_number_fragment_is_not_a_sentence(self) -> None:
        texts = " ".join(self.summarize(
            "### [S2]\nThe PRISMA 2020 statement is an updated guideline for reporting systematic reviews [S2]. "
            "It is listed as Res Synth Methods. 2021;10(1):89 [S2]."))
        self.assertIn("PRISMA 2020 statement", texts)
        self.assertNotIn("2021;10(1):89", texts)


if __name__ == "__main__":
    unittest.main()
