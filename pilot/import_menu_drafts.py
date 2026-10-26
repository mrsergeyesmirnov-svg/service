"""Import private PPTX packs locally on the Academy server. Never publishes or assigns.

Usage: python import_menu_drafts.py /private/menu.zip [--apply]
Default is parse-only: no database connection, no AI calls, no writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from psycopg.types.json import Jsonb
from pptx_ttk import extract_pptx


def read_pack(path):
    packs = []
    with ZipFile(path) as archive:
        files = [i for i in archive.infolist() if i.filename.lower().endswith('.pptx')]
        if not 1 <= len(files) <= 20 or sum(i.file_size for i in files) > 150_000_000:
            raise ValueError('Expected 1–20 PPTX files, total at most 150 MB')
        for info in sorted(files, key=lambda i: i.filename):
            if info.file_size > 20_000_000:
                raise ValueError('A PPTX file exceeds 20 MB')
            raw = archive.read(info)
            cards = extract_pptx(raw)  # Deterministic template import; no AI.
            sections = {card['section'] for card in cards}
            if len(sections) != 1:
                raise ValueError('Each PPTX must contain one menu section')
            packs.append(dict(name=Path(info.filename).name,
                              digest=hashlib.sha256(raw).hexdigest(),
                              section=next(iter(sections)), cards=cards))
    return packs


def import_pack(connection, owner, packs):
    """Caller owns the transaction. Retrying identical files is idempotent."""
    c = connection
    c.execute('SELECT pg_advisory_xact_lock(823412)')
    user = c.execute("SELECT id,restaurant FROM staff WHERE id=%s AND active AND role='manager'",
                     (owner,)).fetchone()
    if not user:
        raise ValueError('Configured owner must be an active service manager')
    output = []
    for pack in packs:
        source = 'menu-pptx-sha256:' + pack['digest']
        existing = c.execute('SELECT id FROM courses WHERE restaurant=%s AND source=%s',
                             (user['restaurant'], source)).fetchall()
        if existing:
            if len(existing) != 1:
                raise ValueError('Duplicate course sources require manual review')
            output.append(dict(section=pack['section'], course_id=existing[0]['id'], duplicate=True))
            continue
        ids = []
        for item in pack['cards']:
            warning = '; '.join(filter(None, [item['warning'],
                'Импорт для проверки. Состав, фото и описание не утверждены.']))
            row = c.execute('''INSERT INTO dish_cards
                (restaurant,created_by,title,section,ingredients,description,allergens,photo,
                 source_name,source_page,source_slot,source_hash,warning,import_method)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pptx')
                ON CONFLICT(restaurant,source_hash,source_page,source_slot) DO NOTHING RETURNING id''',
                (user['restaurant'], owner, item['title'], item['section'], Jsonb(item['ingredients']),
                 item['description'], item['allergens'], item['photo'],
                 'PPTX: ' + pack['name'] + ' · ' + item['source_version'],
                 item['source_page'], item['source_slot'], item['source_hash'], warning)).fetchone()
            if not row:
                row = c.execute('''SELECT id FROM dish_cards WHERE restaurant=%s
                    AND source_hash=%s AND source_page=%s AND source_slot=%s AND NOT archived''',
                    (user['restaurant'], item['source_hash'], item['source_page'], item['source_slot'])).fetchone()
            if not row:
                raise ValueError('An archived source card requires manual review')
            ids.append(row['id'])
        course = c.execute('''INSERT INTO courses
            (author,restaurant,title,kind,body,source,questions,pass_score,published)
            VALUES(%s,%s,%s,'service',%s,%s,'[]',80,false) RETURNING id''',
            (owner, user['restaurant'], pack['section'] + ' · меню MOJO',
             'Черновик раздела. Проверь карточки блюд перед подготовкой тестов и публикацией.', source)).fetchone()
        for position, dish_id in enumerate(ids):
            c.execute('INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,%s)',
                      (course['id'], dish_id, position))
        c.execute('INSERT INTO audit(actor,action,target) VALUES(%s,%s,%s)',
                  (owner, 'menu:import-draft', str(course['id'])))
        output.append(dict(section=pack['section'], course_id=course['id'], cards=len(ids), duplicate=False))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    packs = read_pack(args.archive)
    if args.apply:
        from server import db, OWNER
        with db() as connection:
            result = import_pack(connection, OWNER, packs)
    else:
        result = [dict(section=p['section'], cards=len(p['cards']),
                       missing_photos=sum(x['photo'] is None for x in p['cards']),
                       missing_descriptions=sum(not x['description'].strip() for x in p['cards']),
                       status='draft') for p in packs]
    print(json.dumps(result, ensure_ascii=False))
