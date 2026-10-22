"""Server-graded recall quizzes from manager-approved MOJO dish cards.

Never infer a recipe: only use the ingredients of published, reviewed cards.
Generated questions replace the old 'which ingredient is stated?' quiz when a
course has curated dish chapters. Scoring requires no LLM.
"""
import hashlib
from questions import normalize


def _order(values, salt):
    return sorted(values, key=lambda s: hashlib.sha256((salt + str(s)).encode()).hexdigest())


def _ingredients(chapter):
    seen = set()
    result = []
    for raw in chapter.get("ingredients", []):
        name = " ".join(str(raw).split()).strip(" .,;")
        key = normalize(name)
        if 2 <= len(name) <= 110 and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def approved_card_questions(chapters, course_id):
    cards = [c for c in chapters if c.get("kind") == "dish" and len(_ingredients(c)) >= 2]
    if not cards:
        return []
    questions = []
    selected = cards[:6]
    for card in selected:
        title = card["title"]
        source = f'{card["source"]}, стр. {card["source_page"]}' if card.get("source_page") else card["source"]
        ingredients = _ingredients(card)
        names = _order(ingredients, str(card["dish_id"]))[:min(5, len(ingredients))]
        # Open recall is checked deterministically, based on the approved composition.
        questions.append({
            "type": "ingredients",
            "question": f'Вспомни состав «{title}». Перечисли пять компонентов по памяти (если в карточке меньше — все).',
            "ingredients": [[name] for name in names],
            "options": [],
            "explanation": "Проверь состав по утверждённой карточке блюда, затем повтори пропущенные компоненты.",
            "source": source,
        })
        correct = _order(ingredients, title + "correct")[:min(3, len(ingredients))]
        own = {normalize(x) for x in ingredients}
        other = {}
        for neighbor in cards:
            if neighbor["dish_id"] == card["dish_id"]:
                continue
            for candidate in _ingredients(neighbor):
                key = normalize(candidate)
                if key not in own and len(candidate) <= 110:
                    other.setdefault(key, candidate)
        decoys = _order(list(other.values()), title + "decoy")
        if len(correct) >= 2 and len(decoys) >= 2:
            # Interleave believable ingredients taken from OTHER approved cards.
            options = [correct[0], decoys[0], correct[1], decoys[1]]
            if len(correct) >= 3 and len(decoys) >= 3:
                options.extend([decoys[2], correct[2]])
            questions.append({
                "type": "multiple",
                "question": f'Отметь все компоненты, которые действительно входят в «{title}».',
                "options": options,
                "correct": [i for i, x in enumerate(options) if normalize(x) in own],
                "explanation": "Различай ингредиенты этого блюда и похожих позиций меню. Все варианты взяты из утверждённых карточек.",
                "source": source,
            })
    # Start with a mixture of free answers and multi-select, not blocks of one type.
    return questions[:12]
