"""
اختبارات منطق تصنيف الردود (classify / is_noise) في bot_core.

بتشتغل من غير متصفح ولا playwright:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot_core import classify, is_noise  # noqa: E402


class TestClassifyFemale(unittest.TestCase):
    def test_bare_letter(self):
        for reply in ("f", "F", " f ", "f.", "F!", "*f*"):
            self.assertEqual(classify(reply), "stay", reply)

    def test_letter_with_age(self):
        for reply in ("18f", "f18", "22F", "F22"):
            self.assertEqual(classify(reply), "stay", reply)

    def test_age_as_separate_token(self):
        for reply in ("18 f", "f 18", "im 19 f"):
            self.assertEqual(classify(reply), "stay", reply)

    def test_embedded_in_sentence(self):
        for reply in ("hey im f", "f here", "hi there f"):
            self.assertEqual(classify(reply), "stay", reply)

    def test_explicit_words(self):
        for reply in ("female", "fem", "girl", "im a woman", "lady"):
            self.assertEqual(classify(reply), "stay", reply)

    def test_arabic_words(self):
        for reply in ("بنت", "انثى", "أنا فتاة"):
            self.assertEqual(classify(reply), "stay", reply)


class TestClassifyMale(unittest.TestCase):
    def test_bare_letter(self):
        for reply in ("m", "M", "m.", " M "):
            self.assertEqual(classify(reply), "skip", reply)

    def test_letter_with_age(self):
        for reply in ("22m", "m22", "25 m"):
            self.assertEqual(classify(reply), "skip", reply)

    def test_explicit_words(self):
        for reply in ("male", "boy", "im a male", "ذكر", "ولد"):
            self.assertEqual(classify(reply), "skip", reply)


class TestClassifyUnknown(unittest.TestCase):
    def test_empty(self):
        for reply in ("", "   ", "\n"):
            self.assertEqual(classify(reply), "unknown", repr(reply))

    def test_words_that_merely_contain_f_or_m(self):
        """أهم حالة: كلمات عادية ما تتقراش كتعريف بالجنس."""
        for reply in ("fine", "maybe", "for you", "hello", "morning",
                      "from egypt", "same", "hmm", "lol"):
            self.assertEqual(classify(reply), "unknown", reply)

    def test_questions_are_not_declarations(self):
        """'m or f?' سؤال منهم، مش تعريف بنفسهم."""
        for reply in ("m or f?", "f or m?", "r u f?", "are you m?",
                      "u f?", "انت بنت؟"):
            self.assertEqual(classify(reply), "unknown", reply)

    def test_both_genders_is_ambiguous(self):
        """لو السطر فيه الاتنين من غير علامة استفهام، برضه غامض."""
        for reply in ("m or f", "f or m", "m f"):
            self.assertEqual(classify(reply), "unknown", reply)

    def test_vocatives_are_not_gender(self):
        """'hey man' نداء، مش تعريف — ما نتخطاش بنت بسببه."""
        for reply in ("hey man", "sup dude", "yo bro", "hi guys"):
            self.assertEqual(classify(reply), "unknown", reply)


class TestIsNoise(unittest.TestCase):
    def test_ui_strings_are_noise(self):
        for text in ("typing", "online", "New Chat", "send", "person_add",
                     "a few seconds", "level 5 reached"):
            self.assertTrue(is_noise(text), text)

    def test_short_junk_is_noise(self):
        for text in ("ano", "abc", "xy"):
            self.assertTrue(is_noise(text), text)

    def test_gender_replies_are_not_noise(self):
        """لازم الردود اللي بتحدد الجنس تعدّي من فلتر الضوضاء."""
        for text in ("f", "m", "F", "fem", "boy", "girl", "بنت", "ولد", "18f"):
            self.assertFalse(is_noise(text), text)


class TestClassifyNoiseAgreement(unittest.TestCase):
    def test_no_reply_is_both_classified_and_noise(self):
        """
        أي سطر بيتصنّف كـ F/M المفروض ما يكونش ضوضاء، وأي سطر ضوضاء
        المفروض ما يتصنّفش — عشان ما نضيّعش رد حقيقي ولا نمشي على نص واجهة.
        """
        samples = [
            "f", "m", "18f", "m22", "female", "boy", "بنت", "ولد",
            "typing", "online", "New Chat", "send", "ano", "okay",
            "fine", "maybe", "hello", "m or f?",
        ]
        for text in samples:
            decided = classify(text) != "unknown"
            self.assertFalse(decided and is_noise(text),
                             f"{text!r}: بيتصنّف وبرضه ضوضاء")


if __name__ == "__main__":
    unittest.main()
