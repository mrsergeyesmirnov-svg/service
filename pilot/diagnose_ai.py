"""Synthetic provider probe; redacts credentials and folder from error messages."""
import os
import runpy
import httpx

original = httpx.Response.raise_for_status
def checked(response):
    print("provider_http_status:", response.status_code)
    if response.is_error:
        try:
            error = response.json().get("error", {})
            message = str(error.get("message", "")) if isinstance(error, dict) else str(error)
        except ValueError:
            message = "non-json provider response"
        for name in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID"):
            value = os.getenv(name)
            if value:
                message = message.replace(value, "[redacted]")
        print("provider_error:", message[:500])
    return original(response)
httpx.Response.raise_for_status = checked
runpy.run_path("check_ai.py", run_name="__main__")
