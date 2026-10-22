"""Build review-only recall questions from explicit ingredient bullet lists.

No source document or recipe is stored in this repository. Ambiguous layouts
are skipped. Never publishes, assigns, or changes immutable published courses.
"""
import re
import argparse
import hashlib
import sys
from server import db, course_data, audit
from psycopg.types.json import Jsonb

def rebuild(row, pages=None):
    questions=[]
    for match in re.finditer(r'=== (.*?) ===\s*\n(.*?)(?=\n=== |\Z)', row['body'], re.S):
        heading,body=match.groups()
        if ' • страница ' not in heading or '\ue25f' not in body:continue
        name,page=heading.rsplit(' • страница ',1)
        if not page.isdigit() or (pages and int(page) not in pages):continue
        if re.search(r'[\ue000-\uf8ff/]',name):continue
        raw=body.split('Примечания:',1)[0].split('\ue25f')[1:]
        ingredients=[' '.join(x.split()) for x in raw]
        # Reject table fragments, quantities and ambiguous headings; never guess.
        if not 3<=len(ingredients)<=25 or any(not x or len(x)>80 or re.search(r'\d|===',x) for x in ingredients):continue
        ingredients=list(dict.fromkeys(ingredients))
        ingredients=[part for item in ingredients for part in (['Соль','Перец'] if item in ('Соль\\перец','Соль/перец') else [item])]
        if any('/' in x or '\\' in x or '(' in x for x in ingredients):continue
        source=row['source']+'; учебная карточка «'+name+'», с. '+page
        questions.append(dict(type='ingredients',question='Перечисли полный состав блюда «'+name+'». Запиши каждый компонент с новой строки; соусы укажи отдельными компонентами.',
            ingredients=[[x] for x in ingredients],options=[],
            explanation='В учебной карточке перечислены: '+', '.join(ingredients)+'. Сверь пропуски и лишние компоненты. Состав соусов и допустимые замены проверяются отдельно по актуальным материалам.',source=source[:1000]))
    return questions

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--body-sha',required=True)
    parser.add_argument('--pages',required=True)
    args=parser.parse_args()
    apply=args.apply
    pages={int(p) for p in args.pages.split(',')}
    with db() as c:
        rows=c.execute("SELECT * FROM courses WHERE NOT published AND kind='ttk' ORDER BY id FOR UPDATE").fetchall()
        courses=total=0
        for row in rows:
            if hashlib.sha256(row['body'].encode()).hexdigest()!=args.body_sha:continue
            if any(q.get('type')=='ingredients' for q in row['questions']):continue
            questions=rebuild(row,pages)
            if not questions:continue
            # Keep drafts for review; original source and course identity unchanged.
            clean=course_data(dict(row,questions=questions))[4]
            if apply:
                c.execute('UPDATE courses SET questions=%s WHERE id=%s AND NOT published',(Jsonb(clean),row['id']))
                audit(c,row['author'],'course:recall-draft',row['id'])
            courses+=1;total+=len(clean)
        print({'mode':'drafts_updated' if apply else 'dry_run','courses':courses,'recall_questions':total,'published':0,'assigned':0})
