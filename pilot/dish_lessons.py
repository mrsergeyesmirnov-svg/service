"""Manager-reviewed dish chapters for existing MOJO courses.

Courses and their existing test banks are unchanged. Mapping is separate so
a manager can curate the order; unpublished/archived dishes never reach staff.
"""
import hashlib
from fastapi import HTTPException

MAX_DISHES_PER_COURSE = 80

def dish_chapters(c,course_id,restaurant):
    """None = legacy body (no mapping); [] = mapped, but no publishable dishes."""
    mapped = c.execute(
        "SELECT 1 FROM course_dishes WHERE course_id=%s LIMIT 1",(course_id,)
    ).fetchone()
    if not mapped:
        return None
    rows = c.execute("""SELECT d.id,d.title,d.section,d.ingredients,d.description,
              d.source_name,d.source_page,d.photo IS NOT NULL AS has_photo,d.updated_at
              FROM course_dishes m JOIN dish_cards d ON d.id=m.dish_id
              WHERE m.course_id=%s AND d.restaurant=%s AND d.published AND NOT d.archived
              ORDER BY m.position""",(course_id,restaurant)).fetchall()
    result=[]
    for item in rows:
        signature=hashlib.sha256(
            (str(item["id"])+":"+item["updated_at"].isoformat()).encode()
        ).hexdigest()[:10]
        result.append({
            "id":f"dish-{item['id']}-{signature}",
            "kind":"dish",
            "dish_id":item["id"],
            "title":item["title"],
            "section":item["section"],
            "ingredients":item["ingredients"],
            "description":item["description"],
            "source":item["source_name"],
            "source_page":item["source_page"],
            "has_photo":item["has_photo"]
        })
    return result

def map_details(c,course_id):
    return [row["dish_id"] for row in c.execute(
        "SELECT dish_id FROM course_dishes WHERE course_id=%s ORDER BY position",
        (course_id,)).fetchall()]

def validate_dish_ids(raw):
    if (not isinstance(raw,list) or len(raw)>MAX_DISHES_PER_COURSE
        or any(type(x)!=int or x<=0 for x in raw) or len(raw)!=len(set(raw))):
        raise HTTPException(422,"Укажи до 80 различных карточек блюд")
    return raw

def save_mapping(c,course,ids):
    """Caller must hold a transaction and a FOR UPDATE lock on course row."""
    validate_dish_ids(ids)
    if ids:
        rows=c.execute("""SELECT id FROM dish_cards
                  WHERE id=ANY(%s) AND restaurant=%s AND published AND NOT archived""",
                  (ids,course["restaurant"])).fetchall()
        if {r["id"] for r in rows}!=set(ids):
            raise HTTPException(422,"Один из выбранных рецептов не опубликован или относится к другой точке")
    c.execute("DELETE FROM course_dishes WHERE course_id=%s",(course["id"],))
    for i,dish_id in enumerate(ids):
        c.execute("INSERT INTO course_dishes(course_id,dish_id,position) VALUES(%s,%s,%s)",
                  (course["id"],dish_id,i))
