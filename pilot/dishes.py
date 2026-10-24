"""Private dish-card catalog; import creates drafts, publication requires manager review."""
from io import BytesIO
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool
from PIL import Image
from dish_extract import extract_pdf
from pptx_ttk import extract_pptx, template_pptx

MAX_PDF=20_000_000

async def limited_body(request, limit):
    parts=[];count=0
    async for chunk in request.stream():
        count+=len(chunk)
        if count>limit: raise HTTPException(413,"Файл слишком большой")
        parts.append(chunk)
    return b"".join(parts)

def validate_card(d):
    if not isinstance(d,dict): raise HTTPException(422,"Некорректная карточка")
    result={}
    for k,n in (("title",180),("section",100),("description",4500)):
        v=d.get(k)
        if not isinstance(v,str) or (k!="description" and not v.strip()) or len(v)>n:
            raise HTTPException(422,"Проверьте поле: "+k)
        result[k]=v.strip()
    a=d.get("ingredients")
    if not isinstance(a,list) or len(a)>55 or any(not isinstance(x,str) or not x.strip() or len(x)>180 for x in a):
        raise HTTPException(422,"Проверьте ингредиенты")
    result["ingredients"]=[x.strip() for x in a]
    allergies=d.get("allergens","")
    if not isinstance(allergies,str) or len(allergies)>1200: raise HTTPException(422,"Проверь поле аллергены")
    result["allergens"]=allergies.strip()
    return result

def jpg_thumbnail(data):
    if len(data)>4_000_000: raise HTTPException(413,"Фотография больше 4 МБ")
    try:
        with Image.open(BytesIO(data)) as im:
            if im.width*im.height>20_000_000: raise ValueError("oversized")
            im=im.convert("RGB")
            im.thumbnail((900,650))
            output=BytesIO()
            im.save(output,format="JPEG",quality=80,optimize=True)
            return output.getvalue()
    except (ValueError,OSError):
        raise HTTPException(422,"Нужна фотография JPG/PNG/WebP")

def attach(db,require,manager,scope,audit):
    router=APIRouter(prefix="/api/dishes")

    def find(c,u,cid):
        row=c.execute("SELECT * FROM dish_cards WHERE id=%s",(cid,)).fetchone()
        if not row or (row["restaurant"]!=u["restaurant"] and u["role"]!="manager"):
            raise HTTPException(404,"Карточка не найдена")
        if row["archived"] or (not row["published"] and u["role"] not in ("manager","local")):
            raise HTTPException(404,"Карточка не опубликована")
        return row

    @router.get("")
    def all_cards(request:Request):
        with db() as c:
            u=require(c,request)
            return c.execute("""SELECT id,title,section,ingredients,description,allergens,source_page,
                source_name,warning,published,archived,(photo IS NOT NULL) has_photo
                FROM dish_cards WHERE (%s OR restaurant=%s) AND NOT archived AND (%s OR published)
                ORDER BY section,title,id""",
                (u["role"]=="manager",u["restaurant"],u["role"] in ("manager","local"))).fetchall()

    @router.get("/template")
    def get_template(request:Request):
        with db() as c:
            u=require(c,request);manager(u)
        return Response(template_pptx(),media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition":'attachment; filename="MOJO_TTK_template.pptx"',
                     "Cache-Control":"private,no-store"})

    @router.get("/{cid}/photo")
    def photo(cid:int,request:Request):
        with db() as c:
            u=require(c,request)
            row=find(c,u,cid)
            if row["photo"] is None: raise HTTPException(404,"Фото отсутствует")
            return Response(bytes(row["photo"]),media_type="image/jpeg",headers={"Cache-Control":"private,no-store"})

    @router.post("/import")
    async def import_material(request:Request):
        # Authorize BEFORE reading uploaded material or spending an AI request.
        with db() as c:
            u=require(c,request);manager(u)
            uid,restaurant=u["id"],u["restaurant"]
        filename=(request.query_params.get("filename") or "Материал").split("/")[-1].split("\\")[-1][:120]
        media=request.headers.get("content-type","").split(";")[0].lower()
        pptx=filename.lower().endswith(".pptx") or media=="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        pdf=media=="application/pdf" or filename.lower().endswith(".pdf")
        mode=request.query_params.get("mode","template")
        if mode not in ("template","assist"): raise HTTPException(422,"Неизвестный режим разбора")
        if not (pptx or pdf):raise HTTPException(415,"Выбери PDF или PowerPoint PPTX")
        if not pptx and mode=="assist":raise HTTPException(422,"ИИ-преобразование возможно только для PPTX")
        raw=await limited_body(request,MAX_PDF)
        try:
            extracted=await run_in_threadpool(extract_pptx,raw,mode=="assist") if pptx else await run_in_threadpool(extract_pdf,raw)
        except (ValueError,RuntimeError) as exc:raise HTTPException(422,str(exc))
        import_method="pptx" if pptx else "legacy"
        source=("PPTX: " if pptx else "PDF: ")+filename
        with db() as c:
            u=require(c,request);manager(u)
            if (u["id"],u["restaurant"])!=(uid,restaurant):raise HTTPException(403)
            created=skipped=0
            for item in extracted:
                row=c.execute("""INSERT INTO dish_cards
                  (restaurant,created_by,title,section,ingredients,description,allergens,photo,source_name,
                   source_page,source_slot,source_hash,warning,import_method)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(restaurant,source_hash,source_page,source_slot) DO NOTHING RETURNING id""",
                  (restaurant,uid,item["title"],item["section"],Jsonb(item["ingredients"]),
                   item["description"],item.get("allergens",""),item["photo"],source,
                   item["source_page"],item["source_slot"],item["source_hash"],
                   item["warning"],import_method)).fetchone()
                if row:created+=1
                else:skipped+=1
            audit(c,uid,"dishes:import",f"{created} created, {skipped} duplicated, {import_method}")
        return {"created":created,"skipped":skipped,"status":"draft","format":import_method,
                "review_required":True,"warnings":sum(bool(x["warning"]) for x in extracted),
                "missing_photos":sum(x["photo"] is None for x in extracted)}

    @router.post("")
    async def create(request:Request):
        item=validate_card(await request.json())
        with db() as c:
            u=require(c,request);manager(u)
            row=c.execute("""INSERT INTO dish_cards(restaurant,created_by,title,section,ingredients,description,allergens,source_name)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,'Ручная карточка') RETURNING id""",
                 (u["restaurant"],u["id"],item["title"],item["section"],
                  Jsonb(item["ingredients"]),item["description"],item["allergens"])).fetchone()
            audit(c,u["id"],"dishes:create",row["id"])
            return row

    @router.put("/{cid}")
    async def edit(cid:int,request:Request):
        item=validate_card(await request.json())
        with db() as c:
            u=require(c,request);manager(u);row=find(c,u,cid);scope(u,row["restaurant"])
            c.execute("""UPDATE dish_cards SET title=%s,section=%s,ingredients=%s,description=%s,allergens=%s,
                published=false,updated_at=now() WHERE id=%s""",
                (item["title"],item["section"],Jsonb(item["ingredients"]),item["description"],item["allergens"],cid))
            audit(c,u["id"],"dishes:edit",cid)
        return {"ok":True,"published":False}

    @router.put("/{cid}/photo")
    async def replace_photo(cid:int,request:Request):
        with db() as c:
            u=require(c,request);manager(u);row=find(c,u,cid);scope(u,row["restaurant"])
        result=jpg_thumbnail(await limited_body(request,4_000_000))
        with db() as c:
            u=require(c,request);manager(u);row=find(c,u,cid);scope(u,row["restaurant"])
            c.execute("UPDATE dish_cards SET photo=%s,published=false,updated_at=now() WHERE id=%s",(result,cid))
            audit(c,u["id"],"dishes:photo",cid)
        return {"ok":True,"published":False}

    @router.post("/{cid}/publish")
    async def publish(cid:int,request:Request):
        data=await request.json()
        if data.get("reviewed") is not True: raise HTTPException(422,"Подтвердите проверку по актуальной ТТК")
        with db() as c:
            u=require(c,request);manager(u);row=find(c,u,cid);scope(u,row["restaurant"])
            if not row["ingredients"] or not row["description"] or row["photo"] is None:
                raise HTTPException(409,"Для публикации нужны состав, описание и фото")
            if row["import_method"]=="pptx" and (
                not row["allergens"] or row["allergens"].lower() in
                ("не подтверждено","неизвестно","не указано","нет данных")):
                raise HTTPException(409,"Проверь аллергены по утверждённой ТТК: неизвестно не означает отсутствуют")
            c.execute("UPDATE dish_cards SET published=true,warning=NULL,updated_at=now() WHERE id=%s",(cid,))
            audit(c,u["id"],"dishes:publish",cid)
        return {"ok":True}

    @router.delete("/{cid}")
    def archive(cid:int,request:Request):
        with db() as c:
            u=require(c,request);manager(u);row=find(c,u,cid);scope(u,row["restaurant"])
            c.execute("UPDATE dish_cards SET archived=true,published=false,updated_at=now() WHERE id=%s",(cid,))
            audit(c,u["id"],"dishes:archive",cid)
        return {"ok":True}
    return router
