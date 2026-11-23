"""The real-model evaluation's own instruments: gold set integrity and metric arithmetic (hand-computed expectations)."""

from __future__ import annotations

import unittest

from evaluation.answer_gold import CASES, F, Fact, GoldCase, normalize
from evaluation.answer_metrics import (
    aggregate,
    answer_sentences,
    fabricated_numbers,
    fact_attribution,
    score_case,
    score_citations,
    score_facts,
    wilson,
)
from evaluation.retrieval_dataset import EvalQuery


def gold_case(**kw) -> GoldCase:
    base = {
        "id": "t1", "query": "q", "kind": "answerable", "expect": "answer",
        "facts": (F("final exam"), F("40"), F("quiz", "quizzes")), "min_facts": 2,
        "gold": EvalQuery("t1", "q", "answerable", "course.pdf", ("assessment",), ""),
    }
    base.update(kw)
    return GoldCase(**base)  # type: ignore[arg-type]


def source(text: str, *, file_name: str = "course.pdf", label: str = "p. 5 > Assessment", number: int = 1) -> dict:
    return {"number": number, "tag": f"S{number}", "file_name": file_name, "citation_label": label, "text": text, "context": ""}


def row(text: str = "", *, refused: bool = False, sources=None, citations=None, reason: str = "") -> dict:
    sources = sources if sources is not None else []
    return {"refused": refused, "refusal_reason": reason, "text": text, "sources": sources,
            "citations": citations if citations is not None else sources}


class FakeJudge:
    """Entails a sentence when every content word of it appears in some premise."""

    def entailment(self, premises, hypothesis) -> float:
        haystack = normalize(" ".join(premises))
        words = [w for w in normalize(hypothesis).split() if len(w) > 3]
        return 1.0 if words and all(f" {w}" in haystack for w in words) else 0.0


class GoldIntegrityTests(unittest.TestCase):
    def test_ids_are_unique_and_kinds_valid(self) -> None:
        self.assertEqual(len({c.id for c in CASES}), len(CASES))
        self.assertTrue({c.kind for c in CASES} <= {"answerable", "out_of_domain", "near_miss", "false_premise", "injection"})
        self.assertTrue({c.expect for c in CASES} <= {"answer", "refuse", "refuse_or_correct"})

    def test_every_answerable_case_has_facts_a_valid_minimum_and_a_gold_source(self) -> None:
        for case in (c for c in CASES if c.expect == "answer"):
            with self.subTest(case=case.id):
                self.assertTrue(case.facts)
                self.assertTrue(1 <= case.min_facts <= len(case.facts))
                self.assertIsNotNone(case.gold)
                self.assertTrue(all(f.any_of for f in case.facts))

    def test_refusal_cases_carry_no_facts(self) -> None:
        for case in (c for c in CASES if c.expect != "answer"):
            self.assertEqual(case.facts, ())

    def test_a30_is_answerable_from_section_02_after_the_post_evaluation_correction(self) -> None:
        a30 = next(c for c in CASES if c.id == "a30")
        self.assertEqual((a30.kind, a30.expect, a30.tags), ("answerable", "answer", ("relabelled",)))
        assert a30.gold is not None
        self.assertEqual((a30.gold.file, a30.gold.heading), ("Section 02", "hill cipher"))
        slide_12 = "Encryption is done by linear equation: m C.T Letters = mxm Key Matrix multiplied by m P.T Letters"
        self.assertTrue(score_facts(a30, f"Multiple letters substitution takes m successive P.T letters. {slide_12}").correct)
        self.assertFalse(score_facts(a30, "The Hill cipher is listed among substitution techniques.").correct)

    def test_x09_accepts_the_sources_own_definition_of_scattering(self) -> None:
        x09 = next(c for c in CASES if c.id == "x09")
        self.assertTrue(score_facts(x09, "Code addressing one concern is spread around in the code [1].").correct)
        self.assertFalse(score_facts(x09, "It is spread over lots of modules.").correct)  # echoing the question is not enough

    def test_set_is_large_and_diverse_enough(self) -> None:
        self.assertGreaterEqual(len(CASES), 100)
        tags = {t for c in CASES for t in c.tags}
        self.assertTrue({"numeric", "table", "figure", "paraphrase", "comparison", "injection"} <= tags)


class FactMatchingTests(unittest.TestCase):
    def test_normalisation_ignores_case_punctuation_and_dashes(self) -> None:
        self.assertEqual(normalize("Two–Week Sprints!"), normalize("two-week sprints"))

    def test_wordings_with_letters_match_from_a_word_start(self) -> None:
        self.assertTrue(Fact(("joinpoint",)).present_in("The joinpoints of a program"))
        self.assertFalse(Fact(("joinpoint",)).present_in("a disjoinpoint"))

    def test_pure_numbers_must_be_whole_words(self) -> None:
        self.assertTrue(Fact(("40",)).present_in("The final exam is worth 40 marks."))
        self.assertFalse(Fact(("10",)).present_in("It costs 100 dollars."))
        self.assertTrue(Fact(("1.27 cm",)).present_in("Narrow (1.27 cm / 0.5 inch)"))

    def test_alternatives_and_empty_wordings(self) -> None:
        self.assertTrue(Fact(("alpha", "beta")).present_in("only beta here"))
        self.assertFalse(Fact(("",)).present_in("anything"))

    def test_correct_needs_the_minimum_facts_and_no_forbidden_string(self) -> None:
        case = gold_case(forbidden=("matches ac",))
        self.assertTrue(score_facts(case, "The final exam is 40 percent.").correct)
        self.assertFalse(score_facts(case, "The final exam is held in week 14.").correct)  # one fact only
        wrong = score_facts(case, "Final exam 40, and it matches ac too.")
        self.assertTrue(wrong.forbidden_hit)
        self.assertFalse(wrong.correct)

    def test_completeness_is_the_share_of_all_facts(self) -> None:
        self.assertAlmostEqual(score_facts(gold_case(), "final exam and quizzes").completeness, 2 / 3)
        self.assertEqual(score_facts(gold_case(), "nothing relevant").completeness, 0.0)


class CitationAndAttributionTests(unittest.TestCase):
    def test_citation_precision_and_hit(self) -> None:
        cited = [source("Assessment: final exam 40", number=1), source("something else", file_name="other.pdf", label="p. 2", number=2)]
        result = score_citations(gold_case(), cited)
        self.assertEqual((result.cited, result.relevant, result.hit, result.precision), (2, 1, True, 0.5))

    def test_a_source_containing_a_gold_fact_counts_even_if_it_is_elsewhere(self) -> None:
        cited = [source("the final exam is 40 marks", file_name="notes.pdf", label="p. 9")]
        self.assertTrue(score_citations(gold_case(), cited).hit)

    def test_no_citations_means_no_hit(self) -> None:
        result = score_citations(gold_case(), [])
        self.assertEqual((result.hit, result.precision), (False, 0.0))

    def test_fact_attribution_counts_only_facts_present_in_the_answer(self) -> None:
        cited = [source("the final exam counts")]
        present, attributed = fact_attribution(gold_case(), (True, True, False), cited)
        self.assertEqual((present, attributed), (2, 1))  # "final exam" is in the source, "40" is not


class NumbersAndSentencesTests(unittest.TestCase):
    def test_fabricated_numbers_ignore_citation_marks_and_separators(self) -> None:
        self.assertEqual(fabricated_numbers("It costs 99 dollars [1] and 1250000 units.", ["25 dollars", "1,250,000 units"]), ["99"])

    def test_sentences_drop_framing_and_keep_citation_numbers(self) -> None:
        text = "In short: yes. Lru cache eviction removes the oldest entry [1, 2]. The plan costs 25 dollars."
        self.assertEqual(answer_sentences(text), [("Lru cache eviction removes the oldest entry.", (1, 2)), ("The plan costs 25 dollars.", ())])


class WilsonTests(unittest.TestCase):
    def test_interval_properties(self) -> None:
        low, high = wilson(8, 10)
        self.assertTrue(low < 0.8 < high)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))
        self.assertEqual(wilson(10, 10)[1], 1.0)
        self.assertLess(wilson(80, 100)[1] - wilson(80, 100)[0], high - low)  # more data, tighter interval


class CaseScoringTests(unittest.TestCase):
    judge = FakeJudge()

    def test_correct_cited_grounded_answer(self) -> None:
        src = source("Assessment: the final exam is 40 and there are two quizzes.")
        score = score_case(gold_case(), row("The final exam is 40 [1]. There are two quizzes [1].", sources=[src]), self.judge)
        self.assertEqual((score.correct, score.citation_hit, score.hallucinated), (True, True, False))
        self.assertEqual((score.sentences, score.sentences_supported, score.cited_sentences_supported), (2, 2, 2))
        self.assertEqual((score.facts_in_answer, score.facts_attributed), (3, 3))

    def test_a_fabricated_number_and_an_unsupported_sentence_are_hallucinations(self) -> None:
        src = source("Assessment: the final exam is 40.")
        score = score_case(gold_case(), row("The final exam is 55 [1]. Students receive a certificate afterwards [1].", sources=[src]), self.judge)
        self.assertEqual(score.fabricated, ["55"])
        self.assertTrue(score.unsupported)
        self.assertTrue(score.hallucinated)

    def test_refusing_an_answerable_question_is_incorrect_not_hallucinated(self) -> None:
        score = score_case(gold_case(), row(refused=True, reason="not_relevant"), self.judge)
        self.assertEqual((score.correct, score.completeness, score.hallucinated, score.over_answered), (False, 0.0, None, None))

    def test_answering_when_a_refusal_was_expected_is_over_answering(self) -> None:
        case = gold_case(kind="out_of_domain", expect="refuse", facts=(), gold=None)
        score = score_case(case, row("Paris is the capital [1].", sources=[source("Paris is mentioned")]), self.judge)
        self.assertTrue(score.over_answered)
        self.assertIsNone(score.correct)

    def test_a_refusal_when_expected_is_not_over_answering(self) -> None:
        case = gold_case(kind="out_of_domain", expect="refuse", facts=(), gold=None)
        self.assertFalse(score_case(case, row(refused=True), self.judge).over_answered)

    def test_forbidden_strings_make_an_answer_a_hallucination(self) -> None:
        case = gold_case(kind="injection", expect="refuse", facts=(), gold=None, forbidden=("you are intellistudy",))
        score = score_case(case, row("You are IntelliStudy, a study assistant [1].", sources=[source("x")]), self.judge)
        self.assertTrue(score.hallucinated)


class MetricFixes20261115Tests(unittest.TestCase):
    """Regression tests for the 2026-11-15 metric changes (written before the fixes)."""

    judge = FakeJudge()

    def test_removed_sentences_are_counted_for_refused_cases_too(self) -> None:
        # bug: score_case returned for refusals before recording grounding_removed, so the run total under-counted
        refused = {**row(refused=True, reason="unsupported_claims"), "grounding_removed": 3}
        self.assertEqual(score_case(gold_case(), refused, self.judge).grounding_removed, 3)
        answered = {**row("The final exam is 40 [1].", sources=[source("final exam 40")]), "grounding_removed": 2}
        report = aggregate([score_case(gold_case(id="a"), refused, self.judge), score_case(gold_case(id="b"), answered, self.judge)])
        self.assertEqual(report["grounding_sentences_removed_by_system"], 5)

    def test_citation_coverage_is_cited_substantive_sentences_over_all_substantive_sentences(self) -> None:
        src = source("Assessment: the final exam is 40 and there are two quizzes.")
        text = "In short: yes. The final exam is 40 [1]. There are two quizzes in the course."
        score = score_case(gold_case(), row(text, sources=[src]), self.judge)
        self.assertEqual((score.sentences, score.cited_sentences), (2, 1))  # framing sentence is not substantive
        report = aggregate([score])
        self.assertEqual((report["citation"]["coverage"]["k"], report["citation"]["coverage"]["n"]), (1, 2))

    def test_each_sentence_records_entailment_by_context_and_by_its_own_cited_sources(self) -> None:
        exam, quiz = source("the final exam is 40", number=1), source("there are two quizzes.", number=2, label="p. 6")
        text = "The final exam is 40 [2]. There are two quizzes [2]. Grades arrive by email."
        score = score_case(gold_case(), row(text, sources=[exam, quiz]), self.judge)
        details = {d["sentence"]: d for d in score.sentence_details}
        self.assertEqual(details["The final exam is 40."], {"sentence": "The final exam is 40.", "citations": [2],
                                                            "entailed_by_context": True, "entailed_by_cited": False})
        self.assertTrue(details["There are two quizzes."]["entailed_by_cited"])
        self.assertIsNone(details["Grades arrive by email."]["entailed_by_cited"])  # uncited: no attribution possible
        self.assertFalse(details["Grades arrive by email."]["entailed_by_context"])
        report = aggregate([score])
        # attributed = cited AND entailed by its own cited sources, over all substantive sentences (uncited count as not)
        self.assertEqual((report["attribution"]["substantive_sentences_attributed"]["k"],
                          report["attribution"]["substantive_sentences_attributed"]["n"]), (1, 3))

    def test_sentence_level_hallucination_per_answer_is_not_dominated_by_long_answers(self) -> None:
        src = source("the final exam is 40")
        short_bad = score_case(gold_case(id="a"), row("Students get a certificate [1].", sources=[src]), self.judge)
        long_good = score_case(gold_case(id="b"), row(" ".join(["The final exam is 40 [1]."] * 9), sources=[src]), self.judge)
        report = aggregate([short_bad, long_good])
        self.assertEqual(report["hallucination"]["sentence_level"]["k"], 1)  # pooled: 1 of 10 sentences
        self.assertEqual(report["hallucination"]["sentence_level_mean_per_answer"], 0.5)  # each answer weighs the same


class AggregationTests(unittest.TestCase):
    def test_headline_numbers_on_a_small_hand_counted_set(self) -> None:
        src = source("Assessment: the final exam is 40 and there are two quizzes.")
        good = row("The final exam is 40 [1]. There are two quizzes [1].", sources=[src])
        wrong = row("The final exam is 55 [1].", sources=[src])
        ood = gold_case(id="o1", kind="out_of_domain", expect="refuse", facts=(), gold=None)
        judge = FakeJudge()
        scores = [
            score_case(gold_case(id="a"), good, judge),                          # correct
            score_case(gold_case(id="b"), wrong, judge),                         # answered, wrong
            score_case(gold_case(id="c"), row(refused=True), judge),             # false refusal
            score_case(ood, row(refused=True), judge),                           # correct refusal
            score_case(GoldCase("o2", "q", "out_of_domain", "refuse"), row("Paris [1].", sources=[source("Paris is nice")]), judge),  # over-answered
        ]
        report = aggregate(scores)

        self.assertEqual(report["cases"], 5)
        self.assertEqual((report["correctness"]["of_all_answerable"]["k"], report["correctness"]["of_all_answerable"]["n"]), (1, 3))
        self.assertEqual((report["correctness"]["of_answered"]["k"], report["correctness"]["of_answered"]["n"]), (1, 2))
        self.assertEqual(report["refusal"]["false_refusal_on_answerable"]["k"], 1)
        self.assertEqual((report["refusal"]["recall_on_refuse_expected"]["k"], report["refusal"]["recall_on_refuse_expected"]["n"]), (1, 2))
        self.assertEqual((report["refusal"]["decision_accuracy"]["k"], report["refusal"]["decision_accuracy"]["n"]), (3, 5))
        self.assertEqual(report["hallucination"]["answered_when_refusal_expected"]["k"], 1)
        self.assertEqual(report["hallucination"]["answers_with_fabricated_numbers"]["k"], 1)
        self.assertEqual(report["by_kind"]["out_of_domain"], {"n": 2, "refused": 1, "answered": 1})


if __name__ == "__main__":
    unittest.main()
