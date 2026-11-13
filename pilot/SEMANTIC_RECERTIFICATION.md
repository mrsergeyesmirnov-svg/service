# Semantic ingredient recertification

All seven recertification sections use the same Yandex evaluator. No dish,
ingredient, synonym or abbreviation dictionary is used in this grading path.
Other course exams retain their existing grading behavior.

The published PostgreSQL recipe is frozen when an attempt starts. Submission
locks answers and the selected model before any provider call. Each submit
request assesses one unanswered question and commits its assessment. A retry
continues at the next question; completed questions and historical results
are never regraded. A per-attempt PostgreSQL session lock prevents concurrent
provider calls. A process that dies before saving an assessment can repeat
that provider call, but cannot create two persisted grades.

The provider sees only the dish title, canonical components and answer. Every
component must have a valid ID and a recognized/missing/uncertain decision.
Recognized decisions need exact answer evidence. Overlapping evidence moves
both claims to uncertain. JSON shape, coverage, IDs, quotes, occurrences and
completion status are checked server-side. Transient failures and malformed
responses get one retry; authentication/configuration errors are explicit.
Provider failure never becomes a 0% score.

The final attempt score preserves equal weight per question: the rounded
mean of recognized/total component fractions. Disputes expose a provisional
lower/upper range and leave score/passed null. Official assignment completion
waits for a scoped manager to resolve every disputed component and acknowledge
contradictions. Review requires a reason and answer evidence for credit; it
preserves AI decisions and records the reviewer and time. Review is idempotent.
No schema migration is required; metadata is stored in the existing question
snapshots. Practice attempts with disputes also show a provisional result;
completion of practice allows an official attempt.

## Configuration and validation

Use existing `YANDEX_API_KEY` and `YANDEX_FOLDER_ID` settings.
`YANDEX_RECERTIFICATION_MODEL` defaults to `yandexgpt-5.1`, independently of the
case-training model. The API uses structured output as documented at
https://aistudio.yandex.ru/ru/docs/ai-studio/operations/generation/completions-structured

Run contract, isolated PostgreSQL and UI tests through the repository CI.
These mock provider responses: they prove application behavior, not model quality.

To test actual semantic quality in the configured API environment:

```
RUN_YANDEX_RECERTIFICATION_TESTS=1 RECERTIFICATION_TEST_RESTAURANT=MOJO python -m unittest test_recertification_live
```

This reads every currently published recipe in all seven sections, makes real
Yandex requests for full/reordered answers, typos, omitted components and
instruction injection, and also runs the user's synonym/shorthand/ambiguity
control cases. It writes no recipes, attempts or employee results. It may make
hundreds of paid provider requests. Alternatively, use
`python check_recertification_menu.py MOJO` for only the all-menu cases.
Review the report; a successful mocked CI run is not acceptance of model quality.

Deployment must preserve the browser-login changes observed on the running
server, which differ from main. Do not overwrite that installation wholesale.
Real-menu/Yandex acceptance and Selectel deployment require the server access
that was unavailable in this implementation session; neither is claimed here.
