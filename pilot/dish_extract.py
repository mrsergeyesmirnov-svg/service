"""Extract editable dish drafts and embedded photographs from MOJO station-card PDF.

No OCR or external AI: ambiguous pages must be reviewed by the manager.
"""
import hashlib
import io
import re

import fitz
from PIL import Image

MAX_PAGES = 180
BULLET = "\ue25f"

def cleaned(value):
    return re.sub(r"\s+", " ", value.replace(BULLET, " ").replace("", " ")).strip(" •-\t\r\n")

def source_lines(page):
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                txt = cleaned(span["text"])
                if txt:
                    lines.append((span["bbox"][0], span["bbox"][1], span["size"], txt))
    return sorted(lines, key=lambda x: (round(x[1] / 3), x[0]))

def embedded_photos(page):
    photos = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 1:
            continue
        l, top, right, bottom = block["bbox"]
        if not (l > page.rect.width * .44 and 60 < top < page.rect.height * .79
                and right-l >= 110 and bottom-top >= 100):
            continue
        if block["width"] * block["height"] > 15_000_000:
            continue
        try:
            with Image.open(io.BytesIO(block["image"])) as im:
                if im.width * im.height > 15_000_000:
                    continue
                im = im.convert("RGB")
                im.thumbnail((720, 560))
                out = io.BytesIO()
                im.save(out, "JPEG", quality=79, optimize=True)
                photos.append((top, out.getvalue()))
        except (ValueError, OSError):
            continue
    return sorted(photos, key=lambda x: x[0])

def title_for(lines):
    big = [t for x,y,size,t in lines if 23 <= size <= 52 and 40 < y < 150 and x < 170]
    if big:
        return cleaned(" ".join(big))[:180]
    top = [t for x,y,size,t in lines if size >= 27 and y < 110]
    return cleaned(" ".join(top))[:180] if top else ""

def ingredients_for(lines, start=140, end=370, x_left=45, x_right=160, max_size=18):
    names = []
    for x,y,size,t in lines:
        if start <= y < end and x_left <= x <= x_right and size <= max_size:
            if t not in ("Примечания:", "Рецептура:", "Подача:") and not t.startswith("="):
                if t not in names:
                    names.append(t)
    return names[:45]

def notes_for(lines):
    chunks = [t for x,y,size,t in lines if y >= 405 and x < 495 and not t.lower().startswith("примечания")]
    return cleaned(" ".join(chunks))[:2300]

def parse_page(page, page_number, section):
    lines = source_lines(page)
    photos = embedded_photos(page)
    headings = [t for x,y,size,t in lines if size > 28 and y < 65 and t.isupper() and len(t) < 60]
    if headings:
        section = headings[0]
    title = title_for(lines)
    subtitles = [(y,t) for x,y,size,t in lines if (12.8 <= size <= 18 and 112 < y < 410
                 and 110 < x < 510 and 2 <= len(t.split()) <= 9
                 and t[0].isupper() and not t.endswith((".", ",", ":")))]
    candidates = []
    for y,t in sorted(subtitles):
        if (not candidates or y-candidates[-1][0] >= 85) and t != title and len(t)>11:
            candidates.append((y,t))
    split = len(photos) >= 2 and 2 <= len(candidates) <= len(photos)
    cards = []
    if split:
        for idx,(y,name) in enumerate(candidates[:len(photos)]):
            stop = candidates[idx+1][0] if idx+1 < len(candidates) else page.rect.height
            ingredients = ingredients_for(lines, start=y+8, end=stop, x_left=48, x_right=125, max_size=14)
            notes = [t for x,py,sz,t in lines if y+8 < py < stop and 190 < x < 575 and sz <= 15]
            cards.append((name,ingredients,cleaned(" ".join(notes))[:2000],photos[idx][1]))
    else:
        if not title or title.lower() in ("mojo restaurant","mojo"):
            return [],section
        classic = any(55 <= x < 70 and 140 < y < 360 for x,y,sz,t in lines)
        if classic:
            ingredients = ingredients_for(lines)
        else:
            ingredients = ingredients_for(lines,start=115,end=475,x_left=23,x_right=105,max_size=19)
        ingredients = [v for v in ingredients if v.casefold() not in title.casefold() and v!="(2шт/пор)"]
        note = notes_for(lines)
        if not note:
            side = [t for x,y,sz,t in lines if 128 <= x < 480 and 150 < y < 475 and sz < 20]
            note = cleaned(" ".join(side))[:2300]
        cards.append((title,ingredients,note,photos[0][1] if photos else None))
    result=[]
    for slot,(name,ingredients,description,photo) in enumerate(cards):
        warnings=[]
        if not ingredients: warnings.append("Не удалось уверенно выделить ингредиенты")
        if photo is None: warnings.append("Фото не обнаружено; добавить вручную")
        if len(cards)>1: warnings.append("Несколько блюд на странице: проверьте ингредиенты и фото")
        if len(photos)>1 and not split: warnings.append("Несколько фотографий: проверьте число блюд")
        if "/" in name: warnings.append("Есть варианты блюда: проверьте, нужна ли отдельная карточка")
        result.append(dict(title=name,section=section or "Основное меню",ingredients=ingredients,
                          description=description,source_page=page_number,source_slot=slot,
                          warning="; ".join(warnings),photo=photo))
    return result,section

def extract_pdf(data):
    if len(data)>20_000_000 or not data.startswith(b"%PDF-"):
        raise ValueError("Нужен PDF до 20 МБ")
    try:
        doc=fitz.open(stream=data,filetype="pdf")
    except Exception as exc:
        raise ValueError("Не удалось открыть PDF") from exc
    if doc.is_encrypted or not 0<len(doc)<=MAX_PAGES:
        doc.close()
        raise ValueError("PDF защищён или содержит более 180 страниц")
    result=[]
    section="Основное меню"
    digest=hashlib.sha256(data).hexdigest()
    try:
        for index in range(len(doc)):
            cards,section=parse_page(doc[index],index+1,section)
            for card in cards:
                card["source_hash"]=digest
            result.extend(cards)
    except (ValueError,RuntimeError,fitz.FileDataError) as exc:
        raise ValueError("Не удалось корректно разобрать PDF") from exc
    finally:
        doc.close()
    if not result:
        raise ValueError("Не удалось выделить блюда: требуется PDF с текстовым слоем")
    return result


def photos_anywhere(page):
    """Extract actual embedded dish photos without assuming a PDF slide layout.

    Full-page rasterized screenshots are intentionally NOT treated as food photos.
    A manager may upload a genuine dish image to the resulting private draft.
    """
    photos=[]
    for block in page.get_text("dict").get("blocks",[]):
        if block.get("type")!=1 or not block.get("image"):continue
        rect=fitz.Rect(block["bbox"])
        if rect.width<90 or rect.height<90:continue
        if rect.get_area()>page.rect.get_area()*.84:continue
        if len(block["image"])>6_000_000:continue
        try:
            with Image.open(io.BytesIO(block["image"])) as img:
                if img.width*img.height>15_000_000:continue
                img=img.convert("RGB")
                img.thumbnail((900,650))
                output=io.BytesIO()
                img.save(output,"JPEG",quality=80,optimize=True)
                photos.append((rect.get_area(),output.getvalue()))
        except (OSError,ValueError):
            continue
    return sorted(photos,key=lambda v:v[0],reverse=True)


def extract_pdf_assisted(data):
    """Convert text-based legacy PDFs into reviewable MOJO TTK drafts.

    All AI-mapped facts must be checked against extracted source text. No OCR.
    One slide/page is treated as one dish; multi-dish pages require human review.
    """
    from pptx_ttk import assist_map

    if not data.startswith(b"%PDF-") or not 0<len(data)<=20_000_000:
        raise ValueError("Нужен PDF до 20 МБ")
    try:
        doc=fitz.open(stream=data,filetype="pdf")
    except Exception as exc:
        raise ValueError("Не удалось открыть PDF") from exc
    if doc.is_encrypted or len(doc)==0 or len(doc)>20:
        doc.close()
        raise ValueError("Для ИИ-преобразования PDF нужен файл до 20 страниц. Раздели длинную презентацию.")
    slides=[]
    try:
        for index,page in enumerate(doc,1):
            # The existing strict, coordinate-based PDF parser is not used here.
            texts=[block[4].strip() for block in page.get_text("blocks")
                   if len(block)>=7 and block[6]==0 and isinstance(block[4],str) and block[4].strip()]
            if not texts:
                raise ValueError(
                    f"На странице {index} PDF нет текстового слоя. "
                    "Это скан или слайд-картинка; нужен исходный PPTX или ручное заполнение ТТК.")
            slides.append({"page":index,"texts":texts,"photos":photos_anywhere(page)})
    finally:
        doc.close()
    # The model can map printed text only; its result never bypasses manager review.
    converted=assist_map(slides)
    result=[]
    digest=hashlib.sha256(data).hexdigest()
    for slide in slides:
        fields=converted.get(slide["page"],{})
        photo=slide["photos"][0][1] if slide["photos"] else None
        warnings=["ИИ распределил текст PDF по полям — обязательно проверь по оригиналу"]
        if not fields.get("title"):warnings.append("Название не распознано")
        if not fields.get("ingredients"):warnings.append("Состав не подтверждён")
        if not fields.get("description"):warnings.append("Описание отсутствует")
        if not fields.get("allergens"):warnings.append("Аллергены не подтверждены")
        if len(slide["photos"])>1:warnings.append("На странице несколько фотографий — проверь соответствие")
        if photo is None:warnings.append("Фото блюда не найдено — добавь вручную")
        warnings.append("Если на странице несколько блюд, раздели их вручную")
        result.append({
            "title":str(fields.get("title") or f"Страница {slide['page']} — уточни блюдо")[:180],
            "section":str(fields.get("section") or "Раздел не указан")[:100],
            "ingredients":fields.get("ingredients",[])[:55],
            "description":str(fields.get("description") or "")[:4500],
            "allergens":str(fields.get("allergens") or "")[:1200],
            "source_version":"",
            "photo":photo,"source_page":slide["page"],"source_slot":0,
            "source_hash":digest,"warning":"; ".join(warnings)})
    return result
