"""Source-verified menu recall for MOJO. No OCR guessing, no AI, no exam edits."""
import hashlib
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from dish_lessons import dish_chapters, reviewed_dish_signature

RATINGS = {"know", "hard", "repeat"}


def _norm(text):
    return " ".join(str(text).casefold().split())


def _key(direction, items):
    return hashlib.sha256((direction + "\x1f" + "\x1f".join(_norm(x) for x in items)).encode()).hexdigest()[:24]


def menu_pairs(chapters):
    """Use only exact, manager-approved compositions; group identical reverse prompts."""
    forwards, reverse = [], {}
    for c in chapters:
        if c.get("kind") != "dish":
            continue
        name = str(c.get("title", "")).strip()
        ingredients = []
        seen = set()
        for raw in c.get("ingredients", []):
            item = " ".join(str(raw).split()).strip(" ,.;")
            if 2 <= len(item) <= 180 and _norm(item) not in seen:
                ingredients.append(item)
                seen.add(_norm(item))
        if not name or len(ingredients) < 2:
            continue
        ident = str(c.get("id", c.get("dish_id", "")))
        source = str(c.get("source") or "Утвержденная карточка MOJO")
        page = c.get("source_page")
        if page:
            source += " · стр. " + str(page)
        forwards.append({
            "id": _key("menu-forward", [ident, name, *ingredients]),
            "direction": "forward", "prompt": name,
            "answer": [["Ингредиент", x] for x in ingredients],
            "source": source
        })
        # Different dishes may share the exact same ingredient set.
        # Never grade a reverse card as if it had only one valid title.
        normalized = sorted(_norm(x) for x in ingredients)
        reverse_id = _key("menu-reverse", normalized)
        group = reverse.setdefault(reverse_id, {
            "id": reverse_id, "direction": "reverse",
            "prompt": " · ".join(ingredients), "answer": [], "sources": []
        })
        group["answer"].append(["Название", name])
        if source not in group["sources"]:
            group["sources"].append(source)
    for group in reverse.values():
        group["source"] = "; ".join(group.pop("sources"))
    return forwards + list(reverse.values())


def make_router(db, require, manager, scope, audit):
    router = APIRouter(prefix="/api/menu-cards")

    def load(c, user, cid):
        row = c.execute("""SELECT id,restaurant,published,archived,reviewed_dish_signature
            FROM courses WHERE id=%s""", (cid,)).fetchone()
        if not row or row["archived"] or not row["published"] or row["restaurant"] != user["restaurant"]:
            raise HTTPException(404, "Опубликованный курс не найден")
        # This signature is created when the manager reviews the exact dishes and quiz.
        # A later recipe edit invalidates the old approval; never expose stale recall.
        if not row["reviewed_dish_signature"]:
            return []
        chapters = dish_chapters(c, cid, row["restaurant"])
        if not chapters or reviewed_dish_signature(chapters) != row["reviewed_dish_signature"]:
            return []
        return menu_pairs(chapters)

    @router.get("/{cid}")
    def get_cards(cid: int, request: Request):
        with db() as c:
            user = require(c, request)
            pairs = load(c, user, cid)
            result = c.execute("""SELECT ratings FROM menu_card_progress
                WHERE staff_id=%s AND course_id=%s""", (user["id"], cid)).fetchone()
            saved = result["ratings"] if result else {}
            allowed = {p["id"] for p in pairs}
            return {
                "pairs": pairs,
                "ratings": {k: v for k, v in saved.items() if k in allowed and v in RATINGS},
                "reviewed": bool(pairs)
            }

    @router.post("/{cid}/rating")
    async def rate_card(cid: int, request: Request):
        payload = await request.json()
        if (not isinstance(payload, dict) or set(payload) != {"id", "rating"}
                or not isinstance(payload.get("id"), str) or payload.get("rating") not in RATINGS):
            raise HTTPException(422, "Некорректная оценка карточки")
        with db() as c:
            user = require(c, request)
            pairs = load(c, user, cid)
            if payload["id"] not in {p["id"] for p in pairs}:
                raise HTTPException(422, "Карточка не подтверждена для этого курса")
            c.execute("""INSERT INTO menu_card_progress(staff_id,course_id,ratings)
                VALUES(%s,%s,%s)
                ON CONFLICT(staff_id,course_id) DO UPDATE
                SET ratings=menu_card_progress.ratings || EXCLUDED.ratings,
                    updated_at=now()""",
                (user["id"], cid, Jsonb({payload["id"]: payload["rating"]})))
            return {"saved": True, "id": payload["id"], "rating": payload["rating"]}

    return router
