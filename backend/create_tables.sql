-- admins
CREATE TABLE IF NOT EXISTS admins (
  id SERIAL PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- tickets
CREATE TABLE IF NOT EXISTS tickets (
  id SERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  subject TEXT,
  message TEXT,
  status TEXT DEFAULT 'open',
  admin_reply TEXT,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP
);

-- auto replies
CREATE TABLE IF NOT EXISTS auto_replies (
  id SERIAL PRIMARY KEY,
  trigger TEXT NOT NULL,
  reply TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT now()
);

-- tools (if not exists)
CREATE TABLE IF NOT EXISTS tools (
  id SERIAL PRIMARY KEY,
  name TEXT,
  message TEXT
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_auto_triggers ON auto_replies(trigger);
