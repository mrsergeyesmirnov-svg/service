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
    # One question per DISTINCT dish. Never ask free recall and multiple
    # choice back-to-back about the same recipe.
    selected = cards[:8]
    questions = []
    for index,card in enumerate(selected):
        title = card["title"]
        source = f'{card["source"]}, стр. {card["source_page"]}' if card.get("source_page") else card["source"]
        ingredients = _ingredients(card)
        own = {normalize(x) for x in ingredients}
        other = {}
        for neighbor in cards:
            if neighbor["dish_id"] == card["dish_id"]:
                continue
            for candidate in _ingredients(neighbor):
                key = normalize(candidate)
                if key not in own and len(candidate) <= 110:
                    other.setdefault(key,candidate)
        decoys = _order(list(other.values()),title + "decoy")
        if index % 2 == 1 and len(ingredients) >= 2 and len(decoys) >= 2:
            correct = _order(ingredients,title+"correct")[:min(3,len(ingredients))]
            options = [correct[0],decoys[0],correct[1],decoys[1]]
            if len(correct)>=3 and len(decoys)>=3:
                options.extend([decoys[2],correct[2]])
            options=_order(options,str(course_id)+":"+str(card["dish_id"]))
            questions.append({
                "type":"multiple",
                "question":f'Какие из перечисленных ингредиентов входят в «{title}»?',
                "options":options,
                "correct":[i for i,x in enumerate(options) if normalize(x) in own],
                "explanation":"Сравни ингредиенты блюда с похожими позициями по утверждённым ТТК.",
                "source":source,
            })
        else:
            questions.append({
                "type":"ingredients",
                "question":f'Перечисли по памяти весь состав «{title}». Без подсказок.',
                "ingredients":[[name] for name in ingredients],
                "allowed_extra":[],
                "options":[],
                "explanation":"Проверь состав по утверждённой карточке блюда, затем повтори пропущенные компоненты.",
                "source":source,
            })
    return questions
