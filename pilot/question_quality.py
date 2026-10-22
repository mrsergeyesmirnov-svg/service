"""Conservative review warnings for manager-authored MOJO quiz questions.

Only flags likely defects. The manager decides whether facts are correct.
"""
import re

_BAD_GLYPHS=re.compile(r"[▤▥▦\ufffd]")
_TRIVIAL=re.compile(r"(?:прямо\s+указан|какой\s+(?:компонент|ингредиент)\s+(?:прямо\s+)?указан|согласно\s+станционке.+входит)",re.I)
_CITATION=re.compile(r"(?:с\.|стр\.|страниц)\s*\d+",re.I)

def quality_issues(questions):
    warnings=[]
    for i,q in enumerate(questions,1):
        question=str(q.get("question",""))
        options=q.get("options",[])
        if _BAD_GLYPHS.search(question+" "+" ".join(map(str,options))):
            warnings.append({"question":i,"message":"Повреждённые символы: исправь текст или название блюда."})
        if _TRIVIAL.search(question):
            warnings.append({"question":i,"message":"Шаблонное угадывание ингредиента: замени на вопрос о составе, подаче или сравнении."})
        if q.get("type","single")=="single" and len(options)>=3:
            lens=[len(x.strip()) for x in options]
            if min(lens)>=1 and max(lens)>max(45,4*min(lens)):
                warnings.append({"question":i,"message":"Сильно различается длина вариантов; проверь очевидность ответа."})
        if not str(q.get("source","")).strip():
            warnings.append({"question":i,"message":"Нет документа-источника."})
    return warnings
