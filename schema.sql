CREATE TABLE IF NOT EXISTS "profiles" (
	"hash"	BLOB NOT NULL UNIQUE,
	"type"	INTEGER NOT NULL,
	PRIMARY KEY("hash")
);