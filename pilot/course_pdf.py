"""Read MOJO PDF theories into editable chapters, no OCR or guessed facts.

When a document has clear numbered sections, use those as chapters. Otherwise
keep one chapter per PDF page. All imported chapters remain unpublished drafts.
"""
import bisect
import re

import fitz

MAX_PDF_BYTES = 20_000_000
MAX_PDF_PAGES = 55
MAX_TEXT_CHARS = 118_000
HEADINGS = re.compile(r"(?m)^([1-9]\d?)\.\s+([^\n]{4,115})$")


def _clean(page):
    original = page.get_text("text", sort=True).replace("\x00", "").replace("\r\n", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in original.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _chunks(title, body, source):
    result = []
    while body:
        if len(body) <= 5600:
            piece, body = body, ""
        else:
            end = body.rfind("\n", 1500, 5600)
            if end < 0:
                end = body.rfind(" ", 1500, 5600)
            if end < 0:
                end = 5600
            piece, body = body[:end].strip(), body[end:].strip()
        if piece:
            label = title if not result else title + f" · часть {len(result)+1}"
            result.append(dict(title=label[:180], body=piece, source=source[:500]))
    return result


def course_chapters_from_pdf(data, filename):
    if not data.startswith(b"%PDF-") or len(data) > MAX_PDF_BYTES:
        raise ValueError("Нужен PDF до 20 МБ")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except (ValueError, RuntimeError, fitz.FileDataError) as exc:
        raise ValueError("Не удалось открыть PDF") from exc

    try:
        if doc.is_encrypted or not 0 < len(doc) <= MAX_PDF_PAGES:
            raise ValueError("Нужен незашифрованный PDF до 55 страниц. Большой документ раздели на курсы.")
        pages = [(i, content) for i, page in enumerate(doc, 1) if (content := _clean(page))]
        if not pages:
            raise ValueError("В PDF не найден текст. Для сканов нужен PDF с текстовым слоем.")
        combined = "\n".join(content for _, content in pages)
        offsets = []
        index = 0
        for _, content in pages:
            offsets.append(index)
            index += len(content) + 1
        heading_matches = list(HEADINGS.finditer(combined))
        sections = []
        # ponytail: numbered heading heuristic; manager edits irregular PDFs manually.
        if 2 <= len(heading_matches) <= 50:
            proposed = []
            for j, match in enumerate(heading_matches):
                start = match.start()
                end = heading_matches[j + 1].start() if j+1 < len(heading_matches) else len(combined)
                body = combined[start:end].strip()
                if j == 0 and combined[:start].strip():
                    body = combined[:start].strip() + "\n" + body
                page_idx = bisect.bisect_right(offsets, start) - 1
                page_num = pages[page_idx][0]
                heading = match.group(0).strip()
                proposed.append((heading, body, f"{filename}, стр. {page_num}"))
            # Ignore coincidental numbered lists: substantial sections required.
            if sum(len(body) for _, body, _ in proposed) / len(proposed) >= 120:
                sections = proposed
        if not sections:
            for page_num, body in pages:
                title = body.split("\n", 1)[0][:155] or f"Страница {page_num}"
                sections.append((title, body, f"{filename}, стр. {page_num}"))
        result = []
        for title, body, source in sections:
            result.extend(_chunks(title, body, source))
            if len(result) > 60 or sum(len(x["body"]) for x in result) > MAX_TEXT_CHARS:
                raise ValueError("Материал слишком большой. Раздели PDF на несколько небольших курсов.")
        return result
    finally:
        doc.close()
