"""Acceptance checks for MOJO open ingredient recall.
The examples use free-text style from the iPhone trainee review, not an LLM.
"""
import unittest
from questions import check, clean_question, grade_questions
from fastapi import HTTPException


def recipe(*names, aliases=None):
    groups=[[name] for name in names]
    if aliases:
        for index,terms in aliases.items():
            groups[index].extend(terms)
    return {
        "type":"ingredients",
        "question":"Перечисли состав",
        "ingredients":groups,
        "allowed_extra":[],
        "options":[],
        "source":"MOJO ТТК",
        "explanation":"По утверждённой карточке.",
    }


class FreeTextIngredientRecognition(unittest.TestCase):
    def test_whitespace_only_is_equivalent_to_newline_or_comma(self):
        q=recipe("Рис","Лосось","Нори","Сливочный сыр","Огурец")
        variants=[
            "лосось рис нори сливочный сыр огурец",
            "Лосось, рис, нори, сливочный сыр, огурец",
            "ЛОСОСЬ\nРИС\nНОРИ\nСЛИВОЧНЫЙ СЫР\nОГУРЕЦ",
        ]
        for response in variants:
            with self.subTest(response=response):
                got=check(q,response)
                self.assertEqual(got["fraction"],1)
                self.assertEqual(got["recognized"],5)
                self.assertEqual(got["missing"],[])
                self.assertEqual(got["extra"],[])

    def test_distinguishes_generic_shrimp_and_yuzu_from_precise_recipe(self):
        q=recipe(
            "Рис","Лосось","Нори","Креветка пф отварная",
            "Сливочный сыр","Огурец","Соус юдзу","Кунжут юдзу",
        )
        typed="лосось креветка рис нори юдзу сливочный сыр огурец кунжут"
        got=check(q,typed)
        self.assertEqual(got["recognized"],5)
        self.assertCountEqual(got["missing"],
            ["Креветка пф отварная","Соус юдзу","Кунжут юдзу"])
        partial={item["answer"] for item in got["incomplete"]}
        self.assertTrue({"креветка","юдзу","кунжут"}<=partial)
        self.assertEqual(got["extra"],[])
        self.assertLess(got["fraction"],1)

    def test_avocado_fish_from_iphone_recognizes_actual_seven_components(self):
        q=recipe("Авокадо","Огурец","Нори","Лосось","Тунец",
                 "Креветка","Кальмар","Тобико","Соус юдзу")
        typed="креветка кальмар тунец лосось огурец авокадо нори юдзу"
        got=check(q,typed)
        self.assertEqual(got["recognized"],7)
        self.assertCountEqual(got["missing"],["Тобико","Соус юдзу"])
        self.assertIn("юдзу",{x["answer"] for x in got["incomplete"]})
        self.assertEqual(got["extra"],[])

    def test_long_approved_names_match_without_punctuation_or_conjunction(self):
        q=recipe("Авокадо","Огурец","Авокадо и огурец",
                 "Тунец и авокадо","Лосось и авокадо","Краб",
                 "Лосось","Угорь","Тунец","Тунец и лосось",
                 "Тунец кимчи кинза")
        answer=(
           "авокадо огурец авокадо огурец тунец авокадо "
           "лосось авокадо краб лосось угорь тунец "
           "тунец лосось тунец кимчи кинза"
        )
        got=check(q,answer)
        self.assertEqual(got["fraction"],1)
        self.assertEqual(got["recognized"],11)
        self.assertEqual(got["extra"],[])
        self.assertEqual(got["missing"],[])

    def test_one_word_cannot_satisfy_the_short_and_long_item_twice(self):
        q=recipe("Авокадо","Авокадо и огурец")
        self.assertEqual(check(q,"авокадо огурец")["recognized"],1)
        self.assertEqual(check(q,"авокадо авокадо огурец")["recognized"],2)

    def test_dish_qualified_name_requires_manager_approved_alias(self):
        strict=recipe("Креветка пф отварная")
        self.assertEqual(check(strict,"креветка вареная")["recognized"],0)
        with_alias=recipe("Креветка пф отварная",aliases={
            0:["Креветка вареная"]})
        result=check(with_alias,"креветка варёная")
        self.assertEqual(result["fraction"],1)
        self.assertEqual(result["extra"],[])
        self.assertEqual(result["missing"],[])

    def test_safe_inflections_word_order_and_extra_tokens(self):
        q=recipe("Сливочный сыр","Креветка","Лосось")
        good=check(q,"сыр сливочный, креветкой лосося")
        self.assertEqual(good["fraction"],1)
        bad=check(q,"сыр сливочный, креветка, лосось, рис")
        self.assertEqual(bad["recognized"],3)
        self.assertEqual(bad["extra"],["рис"])
        self.assertLess(bad["fraction"],1)

    def test_no_silent_fuzzy_substrings_or_unsafe_aliases(self):
        q=recipe("Соус юдзу","Кунжут юдзу","Рис")
        r=check(q,"юдзу кунжут рис")
        self.assertLess(r["fraction"],1)
        self.assertIn("Соус юдзу",r["missing"])
        self.assertEqual(check(q,"соус юдзу кунжут юдзу рис")["fraction"],1)

    def test_old_comma_and_line_snapshots_still_grade(self):
        q=recipe("Рис","Лосось","Нори","Сливочный сыр")
        variants=["рис\nлосось\nнори\nсливочный сыр",
                  "рис,лосось,нори,сливочный сыр"]
        for response in variants:
            self.assertEqual(grade_questions([q],[response]),100)
        self.assertEqual(check(q,"лосось")["recognized"],1)
        with self.assertRaises(HTTPException):
            check(q," ")

    def test_manager_specified_alias_validation_retained(self):
        def text(item,name,maxlength):
            value=item.get(name)
            if not isinstance(value,str) or not value.strip():
                raise HTTPException(422,"Не заполнено")
            return value
        q=recipe("Соус юдзу","Кунжут юдзу")
        valid=clean_question(q,text)
        self.assertEqual(valid["ingredients"],q["ingredients"])
        self.assertLess(check(valid,"юдзу")["fraction"],1)


if __name__=="__main__":
    unittest.main()
