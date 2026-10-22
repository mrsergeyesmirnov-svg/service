"""Extract editable theory chapters from a text-layer PDF without inventing content.

PDF images are handled by the existing separate dish-card importer. This
extractor is for servicebooks, theory notes and WOW/SMILE educational PDFs.
"""
import re

import fitz

MAX_PDF_BYTES = 20_000_000
MAX_PDF_PAGES = 55
MAX_TEXT_CHARS = 118_000


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
        result = []
        for page_number, page in enumerate(doc, 1):
            original = page.get_text("text", sort=True)
            original = original.replace("\x00", "").replace("\r\n", "\n")
            # Preserve the actual author text. Only remove empty line noise.
            lines = [re.sub(r"[ \t]+", " ", line).strip()
                     for line in original.splitlines()]
            content = "\n".join(line for line in lines if line).strip()
            if not content:
                continue
            # A long PDF page is split at line boundaries to keep each chapter editable.
            chunks = []
            while content:
                if len(content) <= 5700:
                    chunks.append(content)
                    break
                boundary = content.rfind("\n", 1500, 5700)
                if boundary == -1:
                    boundary = content.rfind(" ", 1500, 5700)
                if boundary == -1:
                    boundary = 5700
                chunks.append(content[:boundary].strip())
                content = content[boundary:].strip()
            for index, chunk in enumerate(chunks, 1):
                first_line = chunk.split("\n", 1)[0][:155]
                title = first_line if len(first_line) >= 4 else f"Страница {page_number}"
                if len(chunks) > 1:
                    title += f" · часть {index}"
                result.append({
                    "title": title[:180],
                    "body": chunk,
                    "source": f"{filename}, стр. {page_number}",
                })
            if len(result) > 60 or sum(len(x["body"]) for x in result) > MAX_TEXT_CHARS:
                raise ValueError("Материал слишком большой. Раздели PDF на несколько небольших курсов.")
        if not result:
            raise ValueError("В PDF не найден текст. Для отсканированных страниц нужен PDF с текстовым слоем.")
        return result
    finally:
        doc.close()
