"""Run inside service-academy-api to diagnose a synthetic AI case. No secrets printed."""
import os
import sys
from fastapi import HTTPException
from cases_api import evaluate_with_yandex

if not os.getenv("YANDEX_API_KEY") or not os.getenv("YANDEX_FOLDER_ID"):
    print("ai_configured: false")
    print("result: missing YANDEX_API_KEY or YANDEX_FOLDER_ID in Academy container")
    sys.exit(2)

print("ai_configured: true")
case={
 "title":"Тест связи с AI Studio",
 "competency":"Учебная рекомендация",
 "action":"Уточнение пожеланий",
 "scenario":"Гость просит помочь выбрать напиток.",
 "source":"Synthetic diagnostics only",
 "criteria":["Уточнить предпочтения гостя","Не выдумывать ассортимент"],
}
try:
    feedback=evaluate_with_yandex(case,"Я спрошу гостя о предпочтениях и предложу только проверенные позиции меню.")
    required={"summary","strengths","improvements","next_step"}
    print("ai_feedback_ok:",required.issubset(feedback))
except HTTPException as e:
    print("ai_feedback_ok: false")
    print("academy_error_code:",e.status_code)
    # Do not print exception details or provider responses; protect credentials and user info.
    sys.exit(1)
