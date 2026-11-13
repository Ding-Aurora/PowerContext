"""Engineering documents are stored and retrieved by real seekdb/OceanBase SQL."""

import hashlib
import os
import re

import pymysql


class DocumentStore:
    def __init__(self):
        self.connection = pymysql.connect(
            host=os.environ.get("SDD_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("SDD_DB_PORT", "2881")),
            user=os.environ.get("SDD_DB_USER", "root"),
            password=os.environ.get("SDD_DB_PASSWORD", ""),
            database=os.environ.get("SDD_DB_NAME", "sdd"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )

    def close(self):
        self.connection.close()

    def initialize(self):
        with self.connection.cursor() as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS sdd_documents (
                path VARCHAR(512) PRIMARY KEY, kind VARCHAR(16) NOT NULL,
                content LONGTEXT NOT NULL, sha256 CHAR(64) NOT NULL
            )""")
        self.connection.commit()

    def ingest(self, root):
        documents = []
        for relative, kind in [("demo/specs", "spec"), ("demo/tests", "test"), ("demo", "code")]:
            paths = (root / relative).glob("*.md" if kind == "spec" else "*.py")
            for path in sorted(paths):
                content = path.read_text(encoding="utf-8")
                documents.append((path.relative_to(root).as_posix(), kind, content,
                                  hashlib.sha256(content.encode()).hexdigest()))
        # Atomic replacement removes stale/deleted sources as well as updating changed specs.
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("DELETE FROM sdd_documents")
                cursor.executemany(
                    "INSERT INTO sdd_documents (path, kind, content, sha256) VALUES (%s,%s,%s,%s)",
                    documents,
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return [{"path": p, "kind": k, "sha256": h} for p, k, _, h in documents]

    def search(self, query):
        terms = list(dict.fromkeys(re.findall(r"[\w-]+", query.lower())))[:16]
        if not terms:
            raise ValueError("Query must contain at least one word")
        # Parameterized lexical retrieval is sufficient for this bounded demonstration.
        predicates = " OR ".join(["LOWER(content) LIKE %s"] * len(terms))
        sql = f"SELECT path, kind, content, sha256 FROM sdd_documents WHERE {predicates} ORDER BY path"
        parameters = ["%" + term.replace("_", r"\_") + "%" for term in terms]
        with self.connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            rows = cursor.fetchall()
        return rows, {"sql": sql, "parameters": parameters, "matched_sources": [r["path"] for r in rows]}
