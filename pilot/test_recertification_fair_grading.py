import unittest
from questions import check, grade_questions


def recall(names, answer, lenient=True):
    q = {'type': 'ingredients', 'ingredients': [[name] for name in names],
         'lenient_recall': lenient}
    return check(q, answer)


class FairRecertificationGrading(unittest.TestCase):
    def test_shorthand_and_word_order(self):
        result = recall(['Рис', 'Нори', 'Лосось', 'Креветка в темпуре',
                         'Спайси соус', 'Соус унаги', 'Кунжут', 'Манго консерв'],
                        'креветка темпура лосось унаги кунжут манго спайси рис нори')
        self.assertEqual(result['recognized'], 8)
        self.assertEqual(result['fraction'], 1)

    def test_real_missing_still_counts(self):
        result = recall(['Свекла', 'Фета', 'Руккола', 'Миндаль', 'Соус винегрет'],
                        'фета руккола свекла миндаль')
        self.assertEqual(result['recognized'], 4)
        self.assertEqual(result['missing'], ['Соус винегрет'])

    def test_one_mention_cannot_credit_two_sauces(self):
        result = recall(['Соус кимчи', 'Соус унаги', 'Томаты свежие'],
                        'соус томаты')
        self.assertEqual(result['recognized'], 1)

    def test_strict_course_grading_unchanged(self):
        self.assertEqual(recall(['Креветка в темпуре', 'Рис'], 'креветка рис', False)['recognized'], 1)

    def test_shortened_recipe_passes(self):
        names = ['Баклажаны жареные во фритюре (в крахмале)', 'Томаты',
                 'Кинза', 'Кунжут', 'Соус к баклажанам (кисло-сладкий, сладкий чили)']
        result = recall(names, 'баклажаны томаты кинза кунжут чили')
        self.assertEqual(result['recognized'], 5)


if __name__ == '__main__':
    unittest.main()
