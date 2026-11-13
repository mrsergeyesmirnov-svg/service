"""Opt-in semantic regressions with real Yandex calls; no employee records written."""
import os
import unittest
from recertification_ai import evaluate_question
from check_recertification_menu import run


@unittest.skipUnless(os.getenv('RUN_YANDEX_RECERTIFICATION_TESTS')=='1',
                     'Live Yandex/menu checks require explicit opt-in and configured credentials')
class LiveSemanticQuality(unittest.TestCase):
    def test_every_published_recipe_in_all_seven_sections(self):
        self.assertTrue(run(os.environ['RECERTIFICATION_TEST_RESTAURANT']))

    def test_user_control_cases_are_tests_not_runtime_exceptions(self):
        cases=[
            ('Поке с лососем и тунцом', ['Рис','Тунец','Лосось','Чука','Соус ореховый том ям'],
             'рис лосось тунец чука ореховый том ям',{0,1,2,3,4}),
            ('Салат со свёклой и фетой',['Свёкла','Фета','Руккола','Миндаль','Соус винегрет'],
             'фета рукола свекла миндаль ореховый соус',{0,1,2,3}),
            ('Томаты кимчи со страчателлой', ['Страчателла','Томаты свежие','Соус кимчи','Оливковое масло','Перец чёрный молотый','Кинза'],
             'томаты кимчи страчателла кинза',{0,1,2,5}),
            ('Контроль сокращения продукта',['Креветка в темпуре','Рис'], 'креветка рис',{0,1}),
            ('Контроль гарнира',['Картофельное пюре','Говяжьи щёчки'],'пюре щечки',{0,1}),
            ('Контроль синонима',['Томаты свежие','Руккола'],'помидоры и рукола',{0,1}),
            ('Контроль похожих продуктов',['Соус кимчи','Соус унаги'],'кимчи',{0}),
        ]
        for title,ingredients,answer,expected in cases:
            with self.subTest(dish=title,answer=answer):
                result=evaluate_question(dict(dish_title=title,question=title,
                    ingredients=[[n] for n in ingredients]),answer)
                self.assertEqual({c['id'] for c in result['components'] if c['status']=='recognized'},expected)

    def test_ambiguity_and_negation_never_inflate_scores(self):
        q=dict(question='Контроль неоднозначности',dish_title='Контроль',
               ingredients=[['Соус кимчи'],['Соус унаги']])
        result=evaluate_question(q,'соус')
        self.assertEqual(result['recognized'],0)
        self.assertTrue(result['needs_review'])
        result=evaluate_question(q,'кимчи не называл, унаги тоже не помню')
        self.assertEqual(result['recognized'],0)
