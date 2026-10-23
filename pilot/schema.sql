CREATE TABLE IF NOT EXISTS staff (
 id BIGINT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('trainee','waiter','manager','local')),
 restaurant TEXT NOT NULL DEFAULT 'MOJO', phone TEXT, active BOOLEAN NOT NULL DEFAULT TRUE,
 bot_started BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS invites (
 token TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('trainee','waiter')),
 restaurant TEXT NOT NULL, created_by BIGINT NOT NULL REFERENCES staff(id), expires_at TIMESTAMPTZ NOT NULL,
 used_by BIGINT REFERENCES staff(id), revoked BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, staff_id BIGINT NOT NULL REFERENCES staff(id), expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
 id BIGSERIAL PRIMARY KEY, author BIGINT NOT NULL REFERENCES staff(id), restaurant TEXT NOT NULL,
 title TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL,
 questions JSONB NOT NULL, pass_score INT NOT NULL CHECK(pass_score BETWEEN 1 AND 100),
 published BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS assignments (
 id BIGSERIAL PRIMARY KEY, staff_id BIGINT NOT NULL REFERENCES staff(id), course_id BIGINT NOT NULL REFERENCES courses(id),
 assigned_by BIGINT NOT NULL REFERENCES staff(id), deadline DATE NOT NULL, max_attempts INT NOT NULL CHECK(max_attempts BETWEEN 1 AND 20),
 acknowledged_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(staff_id,course_id)
);
CREATE TABLE IF NOT EXISTS attempts (
 id BIGSERIAL PRIMARY KEY, assignment_id BIGINT NOT NULL REFERENCES assignments(id), request_id UUID NOT NULL,
 answers JSONB NOT NULL, score INT NOT NULL, passed BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(assignment_id,request_id)
);
CREATE TABLE IF NOT EXISTS outbox (
 id BIGSERIAL PRIMARY KEY, recipient BIGINT NOT NULL REFERENCES staff(id), message TEXT NOT NULL, assignment_id BIGINT REFERENCES assignments(id),
 dedupe TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'pending', tries INT NOT NULL DEFAULT 0,
 next_try TIMESTAMPTZ NOT NULL DEFAULT now(), sent_at TIMESTAMPTZ, error TEXT
);
CREATE TABLE IF NOT EXISTS audit (
 id BIGSERIAL PRIMARY KEY, actor BIGINT, action TEXT NOT NULL, target TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS assignments_staff ON assignments(staff_id);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(state,next_try);

-- Practice cases are separate from scored quizzes: LLM guidance never grants admission.
CREATE TABLE IF NOT EXISTS case_scenarios (
 id BIGSERIAL PRIMARY KEY,
 author BIGINT NOT NULL REFERENCES staff(id),
 restaurant TEXT NOT NULL,
 title TEXT NOT NULL,
 competency TEXT NOT NULL,
 action TEXT NOT NULL,
 scenario TEXT NOT NULL,
 source TEXT NOT NULL,
 criteria JSONB NOT NULL,
 published BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS case_attempts (
 id BIGSERIAL PRIMARY KEY,
 case_id BIGINT NOT NULL REFERENCES case_scenarios(id),
 staff_id BIGINT NOT NULL REFERENCES staff(id),
 request_id UUID NOT NULL,
 answer TEXT NOT NULL,
 feedback JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(case_id,staff_id,request_id)
);
CREATE INDEX IF NOT EXISTS case_attempts_staff ON case_attempts(staff_id,created_at);

-- Independent study never changes mandatory assignments or admission.
CREATE TABLE IF NOT EXISTS learning_progress (
 staff_id BIGINT NOT NULL REFERENCES staff(id), course_id BIGINT NOT NULL REFERENCES courses(id),
 chapter_ids JSONB NOT NULL DEFAULT '[]', updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(staff_id,course_id)
);
CREATE TABLE IF NOT EXISTS learning_attempts (
 id BIGSERIAL PRIMARY KEY, staff_id BIGINT NOT NULL REFERENCES staff(id),
 course_id BIGINT NOT NULL REFERENCES courses(id), request_id UUID NOT NULL,
 answers JSONB NOT NULL, score INT NOT NULL, passed BOOLEAN NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(staff_id,course_id,request_id)
);
-- Published scenarios can be retired without deleting employee attempt history.
ALTER TABLE case_scenarios ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;


-- Private editable dish cards, kept separately from published immutable course versions.
CREATE TABLE IF NOT EXISTS dish_cards (
 id BIGSERIAL PRIMARY KEY,
 restaurant TEXT NOT NULL,
 created_by BIGINT NOT NULL REFERENCES staff(id),
 title TEXT NOT NULL,
 section TEXT NOT NULL,
 ingredients JSONB NOT NULL DEFAULT '[]',
 description TEXT NOT NULL DEFAULT '',
 photo BYTEA,
 source_name TEXT NOT NULL DEFAULT 'Ручная карточка',
 source_page INTEGER,
 source_slot INTEGER NOT NULL DEFAULT 0,
 source_hash TEXT,
 warning TEXT,
 published BOOLEAN NOT NULL DEFAULT FALSE,
 archived BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(restaurant,source_hash,source_page,source_slot)
);
CREATE INDEX IF NOT EXISTS dish_cards_visible ON dish_cards(restaurant,published,archived);


-- Manager-selected published dish cards form clean chapters inside existing courses.
-- Existing quizzes and attempts stay linked to their original course ID.
CREATE TABLE IF NOT EXISTS course_dishes (
 course_id BIGINT NOT NULL REFERENCES courses(id),
 dish_id BIGINT NOT NULL REFERENCES dish_cards(id),
 position INT NOT NULL CHECK(position >= 0),
 PRIMARY KEY(course_id,dish_id),
 UNIQUE(course_id,position)
);


-- Advisory AI practice is not an exam and does not affect course pass status.
CREATE TABLE IF NOT EXISTS dish_practice_attempts (
 id BIGSERIAL PRIMARY KEY,
 staff_id BIGINT NOT NULL REFERENCES staff(id),
 course_id BIGINT NOT NULL REFERENCES courses(id),
 dish_id BIGINT NOT NULL REFERENCES dish_cards(id),
 request_id UUID NOT NULL,
 answer TEXT NOT NULL,
 feedback JSONB,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','failed')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(staff_id,course_id,dish_id,request_id)
);
CREATE INDEX IF NOT EXISTS dish_practice_daily ON dish_practice_attempts(staff_id,created_at);


-- Manager-authored structured chapters for theory of coffee, service and other non-dish courses.
CREATE TABLE IF NOT EXISTS course_text_outline (
 course_id BIGINT PRIMARY KEY REFERENCES courses(id),
 chapters JSONB NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Limit billed retries of one written practice answer, including network-ambiguous attempts.
ALTER TABLE dish_practice_attempts ADD COLUMN IF NOT EXISTS tries INTEGER NOT NULL DEFAULT 1;


-- Preserve exact quiz rubric for any prior attempt when approved menu cards change.
ALTER TABLE learning_attempts ADD COLUMN IF NOT EXISTS questions JSONB NOT NULL DEFAULT '[]';

-- Bound billed Yandex SpeechKit requests without retaining guest audio.
CREATE TABLE IF NOT EXISTS voice_transcriptions (
 id BIGSERIAL PRIMARY KEY,
 staff_id BIGINT NOT NULL REFERENCES staff(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voice_transcriptions_daily ON voice_transcriptions(staff_id,created_at);

-- Archive obsolete tests/courses without deleting staff progress or historical exam results.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS courses_catalog_visibility ON courses(restaurant,published,archived);

-- Preserve submitted case answers independently of the provider transaction.
CREATE TABLE IF NOT EXISTS case_answer_drafts (
 staff_id BIGINT NOT NULL REFERENCES staff(id),
 case_id BIGINT NOT NULL REFERENCES case_scenarios(id),
 request_id UUID NOT NULL,
 answer TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(staff_id,case_id)
);
