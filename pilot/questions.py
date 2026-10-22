"""Deterministic knowledge checks; recipes and aliases must be manager-reviewed."""
import re
from fastapi import HTTPException

def normalize(value):
    return re.sub(r'\s+', ' ', value.casefold().replace('ё','е')).strip(' .-•\t')

def public_question(q):
    return {'type':q.get('type','single'),'question':q['question'],'options':q.get('options',[])}

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
        if not isinstance(answer,str) or not answer.strip() or len(answer)>3000:raise HTTPException(422,'Перечислите состав: один ингредиент на строку')
        submitted={normalize(x) for x in re.split(r'[,;\n]+',answer) if normalize(x)}
        groups=[{normalize(x) for x in group} for group in q['ingredients']]
        missing=[q['ingredients'][i][0] for i,g in enumerate(groups) if not g & submitted]
        approved_other={normalize(x) for x in q.get('allowed_extra',[])}
        extra=sorted(submitted-set().union(*groups)-approved_other)
        return {'fraction':max(0,(len(groups)-len(missing)-len(extra))/len(groups)), 'missing':missing,'extra':extra}
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
