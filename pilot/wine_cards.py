"""Reviewed wine recall cards. No LLM generation or exam grading."""
import hashlib
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb

FIELDS = {'name': 180, 'grape': 140, 'country': 100, 'region': 140, 'source': 260}
RATINGS = {'know', 'hard', 'repeat'}


def validate_wines(payload):
    if not isinstance(payload, dict) or payload.get('reviewed') is not True:
        raise HTTPException(422, 'Подтверди сверку с актуальной винной картой')
    raw = payload.get('cards')
    if not isinstance(raw, list) or len(raw) > 80:
        raise HTTPException(422, 'Не больше 80 винных позиций в курсе')
    cards, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise HTTPException(422, 'Укажи название, сорт, страну, регион и источник')
        card = {}
        for key, limit in FIELDS.items():
            value = item[key]
            if not isinstance(value, str):
                raise HTTPException(422, 'Проверь заполнение карточки')
            value = ' '.join(value.split())
            if not value or len(value) > limit:
                raise HTTPException(422, 'Проверь длину и заполнение поля: ' + key)
            card[key] = value
        normalized_name = card['name'].casefold()
        if normalized_name in seen:
            raise HTTPException(422, 'Название вина повторяется. Укажи отличающуюся позицию винной карты.')
        seen.add(normalized_name)
        cards.append(card)
    return cards


def _key(prefix, values):
    normalized = '\\x1f'.join(' '.join(v.split()).casefold() for v in values)
    return hashlib.sha256((prefix + ':' + normalized).encode('utf-8')).hexdigest()[:24]


def recall_pairs(cards):
    """One forward card per wine; one reverse card per unique origin combination.

    Multiple names can share the same grape/country/region: never pretend that
    a reverse prompt has a unique answer when it does not.
    """
    forward, inverse = [], {}
    for card in cards:
        name, grape, country, region = (card[k] for k in ('name', 'grape', 'country', 'region'))
        forward.append({
            'id': _key('forward', [name]),
            'direction': 'forward',
            'prompt': name,
            'answer': [['Сорт', grape], ['Страна', country], ['Регион', region]],
            'source': card['source'],
        })
        group_id = _key('reverse', [grape, country, region])
        group = inverse.setdefault(group_id, {
            'id': group_id, 'direction': 'reverse',
            'prompt': grape + ' · ' + country + ' · ' + region,
            'answer': [], 'source': [],
        })
        group['answer'].append(['Название', name])
        if card['source'] not in group['source']:
            group['source'].append(card['source'])
    for group in inverse.values():
        group['source'] = '; '.join(group['source'])
    return forward + list(inverse.values())


def make_router(db, require, manager, scope, audit):
    router = APIRouter(prefix='/api/wine-cards')

    @router.get('/{cid}')
    def get_cards(cid: int, request: Request):
        with db() as c:
            user = require(c, request)
            course = c.execute(
                'SELECT id,title,restaurant,published,archived FROM courses WHERE id=%s',
                (cid,)).fetchone()
            if not course or course['archived']:
                raise HTTPException(404, 'Курс не найден')
            if user['restaurant'] != course['restaurant']:
                # Global managers can inspect courses from other restaurants, as elsewhere.
                if user['role'] != 'manager':
                    raise HTTPException(404, 'Курс не найден')
            if not course['published'] and user['role'] not in ('manager', 'local'):
                raise HTTPException(404, 'Курс не опубликован')
            row = c.execute('SELECT cards FROM course_wine_cards WHERE course_id=%s',
                            (cid,)).fetchone()
            cards = row['cards'] if row else []
            pairs = recall_pairs(cards) if course['published'] else []
            progress = c.execute(
                'SELECT ratings FROM wine_card_progress WHERE staff_id=%s AND course_id=%s',
                (user['id'], cid)).fetchone() if course['published'] else None
            ratings = progress['ratings'] if progress else {}
            allowed = {pair['id'] for pair in pairs}
            return {
                'course_id': cid, 'title': course['title'],
                'published': course['published'],
                'cards': cards if user['role'] in ('manager', 'local') else [],
                'pairs': pairs,
                'ratings': {k: v for k, v in ratings.items() if k in allowed},
            }

    @router.post('/{cid}/suggest')
    def suggest_cards(cid: int, request: Request):
        from course_ai import suggest_wine_cards
        with db() as c:
            user = require(c, request)
            manager(user)
            course = c.execute('SELECT id,restaurant,published,archived,body FROM courses WHERE id=%s', (cid,)).fetchone()
            if not course:
                raise HTTPException(404, 'Курс не найден')
            scope(user, course['restaurant'])
            if course['published'] or course['archived']:
                raise HTTPException(409, 'Создай черновик новой версии курса')
            outline = c.execute('SELECT chapters FROM course_text_outline WHERE course_id=%s', (cid,)).fetchone()
            chapters = outline['chapters'] if outline else [{'body':course['body'], 'source':'Материал курса'}]
        return {'cards': suggest_wine_cards(chapters)}

    @router.put('/{cid}')
    async def save_cards(cid: int, request: Request):
        payload = await request.json()
        cards = validate_wines(payload)
        with db() as c:
            user = require(c, request)
            manager(user)
            row = c.execute('SELECT id,restaurant,published,archived FROM courses WHERE id=%s FOR UPDATE',
                            (cid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Курс не найден')
            scope(user, row['restaurant'])
            if row['published'] or row['archived']:
                raise HTTPException(409, 'Опубликованная версия неизменна. Создай новый курс.')
            c.execute("""INSERT INTO course_wine_cards(course_id,cards) VALUES(%s,%s)
                ON CONFLICT(course_id) DO UPDATE SET cards=EXCLUDED.cards,updated_at=now()""",
                (cid, Jsonb(cards)))
            audit(c, user['id'], 'wine:reviewed-draft', cid)
            return {'ok': True, 'cards': len(cards)}

    @router.post('/{cid}/rating')
    async def rate_card(cid: int, request: Request):
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {'id', 'rating'} or payload.get('rating') not in RATINGS:
            raise HTTPException(422, 'Некорректная оценка карточки')
        with db() as c:
            user = require(c, request)
            course = c.execute(
                'SELECT id,restaurant FROM courses WHERE id=%s AND published AND NOT archived',
                (cid,)).fetchone()
            if not course or course['restaurant'] != user['restaurant']:
                raise HTTPException(404, 'Курс не найден')
            row = c.execute('SELECT cards FROM course_wine_cards WHERE course_id=%s',
                            (cid,)).fetchone()
            pairs = recall_pairs(row['cards']) if row else []
            if payload.get('id') not in {pair['id'] for pair in pairs}:
                raise HTTPException(422, 'Карточка не найдена в текущем курсе')
            c.execute("""INSERT INTO wine_card_progress(staff_id,course_id,ratings)
                VALUES(%s,%s,%s)
                ON CONFLICT(staff_id,course_id) DO UPDATE
                SET ratings=wine_card_progress.ratings || EXCLUDED.ratings,updated_at=now()""",
                (user['id'], cid, Jsonb({payload['id']: payload['rating']})))
            return {'saved': True, 'id': payload['id'], 'rating': payload['rating']}

    return router
