# Wine flashcards — implementation contract

Status: isolated feature branch; NOT deployed.

## Purpose
Wine recall practice is an optional intermediate learning stage, never an exam or a substitute for existing assessments.

## Approved source data
Each wine record belongs to a restaurant and contains a stable ID, exact menu name, grape varieties (array), country, region, source document/version, approval status and archival status. No AI inference of wine facts. Incomplete records remain drafts. Manager approval is mandatory before publication. Do not seed fictional wine data into production.

## Both directions
1. Name -> grape varieties, country, region.
2. Grape varieties + country + region -> exact menu name.

The reverse direction must handle multiple wines sharing identical grape/country/region attributes: present all matching approved names or disambiguate using additional *approved* fields. Never mark one of several valid wines wrong.

## Interaction
Show front; tap to reveal back; choose 'Знаю', 'Трудно', or 'Повторить'. Both directions are scheduled separately. 'Трудно' and 'Повторить' return more frequently. Do not show answers before reveal. Restore session and progress after reload, with server-authenticated staff identity. Never trust client-provided staff_id. Escape all user-facing strings.

## Data isolation and migration
Use additive schema only. Do not modify existing learning_attempts, attempts, assignments, courses or grading semantics. New tables for approved wine entries, course-wine relations and staff/direction review progress; constrain FK, restaurant ownership, and unique staff/wine/direction. Enforce manager-only editing and approval, published-course access for learners. Archive rather than delete reviewed wines. Preserve progress when wine details change by recording content revision; reset *only* that wine's affected recall progress after a manager-approved revision.

## UX
Learner home uses light background #F8FAF6, white surfaces, dark green #233F34, lime #D5ED89 sparingly. Keep existing navigation and role routing. Cards use accessible tap/keyboard flip, progress count and clear back navigation. No decorative AI-generated explanations.

## Acceptance tests before merge
- Both directions; multiple grapes; duplicated reverse descriptors; missing fields rejected.
- Approval/restaurant access; unauthorized writes blocked; cross-restaurant reads blocked.
- Progress survives restart; wrong/hard items reappear; separate directional mastery.
- Escaped wine names; mobile Telegram viewport; back navigation.
- Existing course, exam, assignments, role screens and historical attempts unchanged.
- DB migration applies twice safely and preserves all existing data.
- No deployment until tests pass and user approves.
