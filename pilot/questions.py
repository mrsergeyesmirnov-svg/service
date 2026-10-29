"""Deterministic knowledge checks; recipes and aliases must be manager-reviewed."""
import re
from fastapi import HTTPException

def normalize(value):
    return re.sub(r'\s+', ' ', value.casefold().replace('ё','е')).strip(' .-•\t')

def public_question(q):
    return {'type':q.get('type','single'),'question':q['question'],'options':q.get('options',[])}

# Free-form answers are usually dictated or typed in one line. A plain
# whitespace-delimited answer must work, without requiring commas/newlines.
# Do not use fuzzy substring matching: "креветка" is NOT automatically an
# approved synonym for "креветка пф отварная", and "юдзу" is not "соус юдзу".
# Managers can explicitly approve aliases in the question's ingredient groups.
_TOKEN_ALIASES = {
    "лосося": "лосось", "лососем": "лосось",
    "огурца": "огурец", "огурцы": "огурец", "огурцом": "огурец",
    "тунца": "тунец", "тунцом": "тунец",
    "креветки": "креветка", "креветку": "креветка", "креветкой": "креветка",
    "угря": "угорь", "угрем": "угорь",
    "кунжута": "кунжут", "кунжутом": "кунжут",
    "кинзы": "кинза", "кинзой": "кинза",
    "сыра": "сыр", "сыром": "сыр",
    "соуса": "соус", "соусом": "соус",
    "авокадо": "авокадо",
}
_JOINERS = {"и"}
def ingredient_words(value):
    """Stable word tokens: punctuation / lettercase / ё / safe inflections."""
    value = normalize(value).replace("п/ф", "пф")
    words = re.findall(r"[^\W_]+",value,flags=re.UNICODE)
    return tuple(_TOKEN_ALIASES.get(w,w) for w in words if w not in _JOINERS)


def _answer_segments(answer):
    """Keep explicit comma/newline boundaries, accept phrases without them."""
    return [ingredient_words(part) for part in re.split(r"[,;\n]+",answer)
            if ingredient_words(part)]


def _consume_phrase(segments, masks, phrase):
    """Consume one approved ingredient occurrence; never reuse words twice."""
    if not phrase:
        return False
    n=len(phrase)
    for line,words in enumerate(segments):
        for start in range(len(words)-n+1):
            if any(masks[line][j] for j in range(start,start+n)):
                continue
            span=words[start:start+n]
            # Two-word names with reversed word order are a safe grammatical
            # variation ("сыр сливочный" / "сливочный сыр").
            if span==phrase or (n==2 and span==phrase[::-1]):
                for j in range(start,start+n):
                    masks[line][j]=True
                return True
    return False


def grade_ingredient_answer(q, answer):
    segments=_answer_segments(answer)
    masks=[[False]*len(part) for part in segments]
    groups=[[ingredient_words(alias) for alias in group] for group in q["ingredients"]]
    # Longest approved names first. Without this "авокадо" would steal the
    # "авокадо и огурец" occurrence, making a complete answer look wrong.
    priorities=sorted(range(len(groups)),
                      key=lambda i:(-max(len(w) for w in groups[i]),i))
    hits=set()
    for i in priorities:
        for phrase in sorted(groups[i],key=len,reverse=True):
            if _consume_phrase(segments,masks,phrase):
                hits.add(i)
                break
    missing=[q["ingredients"][i][0] for i in range(len(groups)) if i not in hits]
    for raw in q.get("allowed_extra",[]):
        _consume_phrase(segments,masks,ingredient_words(raw))
    extras=[]
    incomplete=[]
    # Do not call a partial name "wrong" AND "missing" simultaneously.
    # It gets zero credit, but the learner sees exactly which qualifier to add.
    pending=[(i,alias) for i in range(len(groups)) if i not in hits
             for alias in groups[i]]
    for li,part in enumerate(segments):
        j=0
        while j<len(part):
            if masks[li][j]:
                j+=1
                continue
            word=part[j]
            possible=[q["ingredients"][i][0] for i,alias in pending
                      if word in alias and len(alias)>1]
            if possible:
                incomplete.append(dict(answer=word,expected=list(dict.fromkeys(possible))[:3]))
            else:
                extras.append(word)
            j+=1
    unique_extras=list(dict.fromkeys(extras))
    # Extra words are genuine incorrect additions. Incomplete qualifiers are
    # counted in missing, not penalized a second time as extras.
    fraction=max(0,(len(hits)-len(unique_extras))/len(groups))
    return dict(fraction=fraction,missing=missing,extra=unique_extras,
                recognized=len(hits),total=len(groups),incomplete=incomplete)


def check(q, answer):
    kind=q.get('type','single')
    if kind=='single':
        if type(answer)!=int or not 0<=answer<len(q['options']):raise HTTPException(422,'Выберите ответ')
        return {'fraction':int(answer==q['correct'])}
    if kind=='multiple':
        if not isinstance(answer,list) or not answer or any(type(x)!=int or not 0<=x<len(q['options']) for x in answer) or len(set(answer))!=len(answer):
            raise HTTPException(422,'Отметьте подходящие варианты')
        expected=set(q['correct']); chosen=set(answer)
        return {'fraction':int(expected==chosen),'missing':[q['options'][i] for i in sorted(expected-chosen)],'extra':[q['options'][i] for i in sorted(chosen-expected)]}
    if kind=='ingredients':
        if not isinstance(answer,str) or not answer.strip() or len(answer)>3000:
            raise HTTPException(422,'Перечислите состав блюда')
        return grade_ingredient_answer(q,answer)
    raise HTTPException(422,'Неизвестный формат вопроса')

def grade_questions(qs, answers):
    if not isinstance(answers,list) or len(answers)!=len(qs) or not qs:raise HTTPException(422,'Ответьте на каждый вопрос')
    return round(100*sum(check(q,a)['fraction'] for q,a in zip(qs,answers))/len(qs))

def clean_question(q, text):
    kind=q.get('type','single')
    base=dict(type=kind,question=text(q,'question',1000),explanation=text(q,'explanation',3000),source=text(q,'source',1000))
    if kind=='ingredients':
        groups=q.get('ingredients')
        if not isinstance(groups,list) or not 1<=len(groups)<=40:raise HTTPException(422,'Укажите проверенный состав')
        seen=set()
        for group in groups:
            if not isinstance(group,list) or not group or any(not isinstance(x,str) or not normalize(x) or len(x)>150 for x in group):raise HTTPException(422,'Проверьте названия ингредиентов')
            aliases={normalize(x) for x in group}
            if seen & aliases:raise HTTPException(422,'Названия разных ингредиентов пересекаются')
            seen |= aliases
        return dict(base,ingredients=groups,options=[])
    if kind not in ('single','multiple'):raise HTTPException(422,'Неизвестный формат вопроса')
    options=q.get('options'); correct=q.get('correct')
    if not isinstance(options,list) or not 2<=len(options)<=20 or any(not isinstance(x,str) or not x.strip() or len(x)>1000 for x in options):raise HTTPException(422,'Проверьте варианты ответа')
    if len({normalize(x) for x in options})!=len(options):raise HTTPException(422,'Варианты повторяются')
    indices=[correct] if kind=='single' else correct
    if not isinstance(indices,list) or not indices or any(type(x)!=int or not 0<=x<len(options) for x in indices) or len(set(indices))!=len(indices):raise HTTPException(422,'Проверьте правильные ответы')
    return dict(base,options=options,correct=correct)
