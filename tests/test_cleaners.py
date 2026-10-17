"""Tests for safe text normalisation in :mod:`ai.ingestion.cleaners`."""

from __future__ import annotations

import unittest

from ai.ingestion.cleaners import clean_text, normalize_unicode


class MathPreservationTests(unittest.TestCase):
    def test_superscripts_survive(self) -> None:
        self.assertEqual(clean_text("x² + y² = z²"), "x² + y² = z²")
        self.assertEqual(clean_text("E = mc², a³, 10⁹"), "E = mc², a³, 10⁹")

    def test_subscripts_survive(self) -> None:
        self.assertEqual(clean_text("H₂O and CO₂"), "H₂O and CO₂")
        self.assertEqual(clean_text("xₙ₊₁ = xₙ"), "xₙ₊₁ = xₙ")

    def test_scientific_notation_survives(self) -> None:
        for expression in ("1.5×10⁻³ m", "6.022e23", "2.5E-4", "3 × 10⁸ m/s"):
            self.assertEqual(clean_text(expression), expression)

    def test_fractions_and_number_sets_survive(self) -> None:
        self.assertEqual(clean_text("½ cup and ¾ turn"), "½ cup and ¾ turn")
        self.assertEqual(clean_text("f: ℝ → ℝ, n ∈ ℕ"), "f: ℝ → ℝ, n ∈ ℕ")

    def test_math_operators_untouched(self) -> None:
        text = "∀x ∈ A: x ≤ y ∧ ∑ᵢ aᵢ ≥ 0 ∫ f(x) dx"
        self.assertEqual(clean_text(text), text)

    def test_ascii_fast_path_is_identity(self) -> None:
        self.assertEqual(normalize_unicode("plain ascii"), "plain ascii")


class PresentationArtefactTests(unittest.TestCase):
    def test_ligatures_are_expanded(self) -> None:
        self.assertEqual(clean_text("ﬁnal ﬂow oﬃce"), "final flow office")

    def test_fullwidth_and_nbsp_are_normalised(self) -> None:
        self.assertEqual(clean_text("ｆｕｌｌ\u00a0width"), "full width")

    def test_control_characters_are_removed(self) -> None:
        self.assertEqual(clean_text("a\x00b\x0cc"), "abc")

    def test_blank_lines_are_collapsed(self) -> None:
        self.assertEqual(clean_text("a\n\n\n\nb"), "a\n\nb")


class HyphenJoiningTests(unittest.TestCase):
    def test_soft_wrapped_word_is_rejoined(self) -> None:
        self.assertEqual(clean_text("inter-\nnational"), "international")
        self.assertEqual(clean_text("informa-\ntion retrieval"), "information retrieval")

    def test_compound_with_known_prefix_keeps_hyphen(self) -> None:
        self.assertEqual(clean_text("well-\nknown"), "well-known")
        self.assertEqual(clean_text("self-\nattention"), "self-attention")
        self.assertEqual(clean_text("non-\nlinear"), "non-linear")

    def test_existing_compound_keeps_hyphens(self) -> None:
        self.assertEqual(clean_text("state-of-the-\nart"), "state-of-the-art")
        self.assertEqual(clean_text("mean-field-\ntheory"), "mean-field-theory")

    def test_hyphen_before_uppercase_or_digit_is_kept(self) -> None:
        self.assertEqual(clean_text("Anglo-\nSaxon"), "Anglo-Saxon")
        self.assertEqual(clean_text("x-\n2"), "x-2")

    def test_exponent_sign_is_never_swallowed(self) -> None:
        self.assertEqual(clean_text("6.02E-\n23"), "6.02E-23")
        self.assertEqual(clean_text("1e-\n5"), "1e-5")

    def test_dash_bullets_are_left_alone(self) -> None:
        self.assertEqual(clean_text("item one -\ntwo"), "item one -\ntwo")
        self.assertEqual(clean_text("- first\n- second"), "- first\n- second")

    def test_normal_hyphens_inside_a_line_are_untouched(self) -> None:
        self.assertEqual(clean_text("a well-known, state-of-the-art tool"),
                         "a well-known, state-of-the-art tool")


if __name__ == "__main__":
    unittest.main()
