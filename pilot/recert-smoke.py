"""Synthetic real-provider check; no database writes or employee data."""
import sys
from fastapi import HTTPException
from recertification_ai import evaluate_batch

def main():
    q = {"ingredients": [["Креветка в темпуре"], ["Рис"], ["Нори"]]}
    try:
        rows = evaluate_batch([q, q], ["креветка рис нори", "креветка рис"])
    except HTTPException as exc:
        print("AI smoke FAILED: Academy HTTP", exc.status_code)
        return 1
    for row in rows:
        print(row)
    if [r["recognized"] for r in rows] != [3, 2]:
        print("AI smoke FAILED: shorthand or omission mismatch")
        return 1
    print("AI smoke PASSED: shorthand accepted, omitted ingredient missing")
    return 0

if __name__ == "__main__":
    sys.exit(main())
