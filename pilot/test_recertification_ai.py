import unittest
from unittest.mock import patch
from fastapi import HTTPException
from recertification_ai import _validate, evaluate_attempt


def q(*ingredients):
    return {'type': 'ingredients', 'ingredients': [[x] for x in ingredients]}


class SemanticRecertification(unittest.TestCase):
    def test_validate_indices_and_missing(self):
        result = _validate({'results': [{'recognized': [0, 2]}]},
                           [q('Рис', 'Нори', 'Креветка в темпуре')])[0]
        self.assertEqual(result['recognized'], 2)
        self.assertEqual(result['missing'], ['Нори'])
        self.assertAlmostEqual(result['fraction'], 2/3)

    def test_reject_hallucinated_or_duplicate_indices(self):
        for indices in ([0, 0], [3], [-1], ['0']):
            with self.assertRaises(ValueError):
                _validate({'results': [{'recognized': indices}]}, [q('Рис', 'Нори')])

    def test_provider_failure_does_not_grade(self):
        with patch('recertification_ai.evaluate_batch', side_effect=HTTPException(503, 'unavailable')):
            with self.assertRaises(HTTPException):
                evaluate_attempt([q('Рис')], ['рис'])

    def test_batches_and_scores(self):
        questions = [q('Рис', 'Нори') for _ in range(6)]
        with patch('recertification_ai.evaluate_batch', side_effect=lambda qs, ans: [
                {'fraction': 0.5, 'recognized': 1, 'total': 2, 'missing': ['Нори']} for _ in qs]) as mock:
            score, reviews = evaluate_attempt(questions, ['рис'] * 6)
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(score, 50)
        self.assertEqual(len(reviews), 6)


if __name__ == '__main__':
    unittest.main()
