"""MOJO in-person training calendar: verified events and registrations, no fake data."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request

def validated_event(data):
    if not isinstance(data, dict):
        raise HTTPException(422, "Заполни мероприятие")
    title = data.get("title")
    location = data.get("location")
    description = data.get("description", "")
    try:
        starts_at = datetime.fromisoformat(data.get("starts_at", "").replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, "Укажи дату и время мероприятия")
    if (not isinstance(title, str) or not 3 <= len(title.strip()) <= 180
            or not isinstance(location, str) or not 2 <= len(location.strip()) <= 180
            or not isinstance(description, str) or len(description) > 2000
            or starts_at.tzinfo is None
            or not datetime.now(timezone.utc) + timedelta(minutes=10) < starts_at < datetime.now(timezone.utc) + timedelta(days=730)):
        raise HTTPException(422, "Проверь название, место и будущую дату")
    return title.strip(), description.strip(), location.strip(), starts_at

def make_events_router(db, require, manager, scope, audit):
    router = APIRouter(prefix="/api/events")

    @router.get("")
    def listing(request: Request):
        with db() as c:
            u = require(c, request)
            can_manage = u["role"] in ("manager", "local")
            rows = c.execute("""
                SELECT e.id,e.title,e.description,e.location,e.starts_at,e.published,e.cancelled,
                  (SELECT count(*) FROM event_signups s WHERE s.event_id=e.id) AS participants,
                  EXISTS(SELECT 1 FROM event_signups s WHERE s.event_id=e.id AND s.staff_id=%s) AS registered
                FROM service_events e WHERE (%s OR e.restaurant=%s)
                  AND (%s OR (e.published AND NOT e.cancelled AND e.starts_at>now()))
                ORDER BY e.starts_at ASC, e.id ASC""",
                (u["id"], u["role"] == "manager", u["restaurant"], can_manage)).fetchall()
            return rows

    @router.post("")
    async def create(request: Request):
        data = await request.json()
        title, description, location, start = validated_event(data)
        with db() as c:
            u = require(c, request); manager(u)
            item = c.execute("""INSERT INTO service_events
                (title,description,location,starts_at,created_by,restaurant)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                (title, description, location, start, u["id"], u["restaurant"])).fetchone()
            audit(c, u["id"], "events:create", item["id"])
            return {"id": item["id"], "published": False}

    @router.put("/{event_id}")
    async def edit(event_id: int, request: Request):
        data = await request.json()
        title, description, location, start = validated_event(data)
        with db() as c:
            u = require(c, request); manager(u)
            event = c.execute("SELECT * FROM service_events WHERE id=%s FOR UPDATE", (event_id,)).fetchone()
            if not event: raise HTTPException(404, "Мероприятие не найдено")
            scope(u, event["restaurant"])
            if event["published"] or event["cancelled"]:
                raise HTTPException(409, "Опубликованное мероприятие нельзя изменять. Отмени его и создай новое.")
            c.execute("""UPDATE service_events SET title=%s,description=%s,location=%s,starts_at=%s
                         WHERE id=%s""", (title, description, location, start, event_id))
            audit(c, u["id"], "events:edit", event_id)
            return {"ok": True}

    @router.post("/{event_id}/publish")
    def publish(event_id: int, request: Request):
        with db() as c:
            u = require(c, request); manager(u)
            event = c.execute("SELECT * FROM service_events WHERE id=%s FOR UPDATE", (event_id,)).fetchone()
            if not event: raise HTTPException(404)
            scope(u, event["restaurant"])
            if event["cancelled"] or event["starts_at"] <= datetime.now(timezone.utc):
                raise HTTPException(409, "Нельзя публиковать отменённое или прошедшее мероприятие")
            c.execute("UPDATE service_events SET published=TRUE WHERE id=%s", (event_id,))
            audit(c, u["id"], "events:publish", event_id)
            return {"ok": True}

    @router.post("/{event_id}/cancel")
    def cancel(event_id: int, request: Request):
        with db() as c:
            u = require(c, request); manager(u)
            event = c.execute("SELECT * FROM service_events WHERE id=%s FOR UPDATE", (event_id,)).fetchone()
            if not event: raise HTTPException(404)
            scope(u, event["restaurant"])
            c.execute("UPDATE service_events SET cancelled=TRUE,published=FALSE WHERE id=%s", (event_id,))
            audit(c, u["id"], "events:cancel", event_id)
            return {"ok": True}

    @router.post("/{event_id}/signup")
    def signup(event_id: int, request: Request):
        with db() as c:
            u = require(c, request)
            event = c.execute("""SELECT * FROM service_events
                      WHERE id=%s AND restaurant=%s AND published AND NOT cancelled
                         AND starts_at>now() FOR UPDATE""", (event_id, u["restaurant"])).fetchone()
            if not event: raise HTTPException(404, "Запись на мероприятие недоступна")
            c.execute("""INSERT INTO event_signups(event_id,staff_id) VALUES(%s,%s)
                         ON CONFLICT DO NOTHING""", (event_id, u["id"]))
            audit(c, u["id"], "events:signup", event_id)
            return {"registered": True}

    @router.delete("/{event_id}/signup")
    def withdraw(event_id: int, request: Request):
        with db() as c:
            u = require(c, request)
            event = c.execute("""SELECT * FROM service_events
                        WHERE id=%s AND restaurant=%s AND starts_at>now()""",
                        (event_id, u["restaurant"])).fetchone()
            if not event: raise HTTPException(404, "Запись недоступна")
            c.execute("DELETE FROM event_signups WHERE event_id=%s AND staff_id=%s", (event_id, u["id"]))
            audit(c, u["id"], "events:withdraw", event_id)
            return {"registered": False}

    @router.get("/{event_id}/participants")
    def participants(event_id: int, request: Request):
        with db() as c:
            u = require(c, request); manager(u)
            event = c.execute("SELECT restaurant FROM service_events WHERE id=%s", (event_id,)).fetchone()
            if not event: raise HTTPException(404)
            scope(u, event["restaurant"])
            return c.execute("""SELECT s.id,s.name,s.role FROM event_signups r
                        JOIN staff s ON s.id=r.staff_id WHERE r.event_id=%s ORDER BY s.name""",
                        (event_id,)).fetchall()

    return router
