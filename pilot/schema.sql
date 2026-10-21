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
