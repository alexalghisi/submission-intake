CREATE TABLE IF NOT EXISTS submissions (
    id            uuid PRIMARY KEY,
    message_id    text NOT NULL UNIQUE,
    content_hash  text NOT NULL,
    raw_key       text NOT NULL,
    sender        text NOT NULL,
    subject       text NOT NULL,
    status        text NOT NULL CHECK (status IN ('received', 'processing', 'ready', 'needs_review', 'failed')),
    attempts      integer NOT NULL DEFAULT 0,
    result        jsonb,
    error         text,
    received_at   timestamptz NOT NULL DEFAULT now(),
    processed_at  timestamptz
);

CREATE INDEX IF NOT EXISTS submissions_review ON submissions (received_at) WHERE status = 'needs_review';

CREATE TABLE IF NOT EXISTS documents (
    submission_id  uuid NOT NULL REFERENCES submissions (id) ON DELETE CASCADE,
    id             text NOT NULL,
    filename       text NOT NULL,
    kind           text NOT NULL,
    chars          integer NOT NULL,
    PRIMARY KEY (submission_id, id)
);
