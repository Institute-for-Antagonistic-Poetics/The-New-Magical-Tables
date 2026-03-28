from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS system (
    id              INTEGER PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS source (
    id              INTEGER PRIMARY KEY,
    system_id       INTEGER NOT NULL REFERENCES system(id) ON DELETE CASCADE,
    short_title     TEXT NOT NULL,
    full_title      TEXT,
    edition         TEXT,
    year            INTEGER,
    citation        TEXT,
    url             TEXT,
    UNIQUE(system_id, short_title, edition)
);

CREATE TABLE IF NOT EXISTS locus (
    id              INTEGER PRIMARY KEY,
    system_id       INTEGER REFERENCES system(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description     TEXT,
    extra_json      TEXT,
    UNIQUE(kind, normalized_name, system_id)
);

CREATE TABLE IF NOT EXISTS alias (
    id               INTEGER PRIMARY KEY,
    locus_id         INTEGER NOT NULL REFERENCES locus(id) ON DELETE CASCADE,
    alias            TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language         TEXT,
    script           TEXT,
    transliteration_scheme TEXT,
    is_primary       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(locus_id, normalized_alias)
);

CREATE TABLE IF NOT EXISTS relation_type (
    id              INTEGER PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    forward_label   TEXT NOT NULL,
    reverse_label   TEXT,
    is_symmetric    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assertion (
    id               INTEGER PRIMARY KEY,
    subject_locus_id INTEGER NOT NULL REFERENCES locus(id) ON DELETE CASCADE,
    relation_type_id INTEGER NOT NULL REFERENCES relation_type(id) ON DELETE CASCADE,
    object_locus_id  INTEGER NOT NULL REFERENCES locus(id) ON DELETE CASCADE,
    source_id        INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    source_locator   TEXT,
    note             TEXT,
    confidence       REAL,
    variant_group    TEXT,
    is_editorial     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(subject_locus_id, relation_type_id, object_locus_id, source_id, source_locator)
);

CREATE INDEX IF NOT EXISTS idx_locus_kind_name ON locus(kind, normalized_name);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON alias(normalized_alias);
CREATE INDEX IF NOT EXISTS idx_assertion_subject ON assertion(subject_locus_id);
CREATE INDEX IF NOT EXISTS idx_assertion_object ON assertion(object_locus_id);
CREATE INDEX IF NOT EXISTS idx_assertion_relation ON assertion(relation_type_id);
CREATE INDEX IF NOT EXISTS idx_assertion_source ON assertion(source_id);
"""


@dataclass(frozen=True)
class Locus:
    id: Optional[int]
    system_id: Optional[int]
    kind: str
    canonical_name: str
    normalized_name: str
    description: Optional[str] = None
    extra: Optional[dict] = None


@dataclass(frozen=True)
class Alias:
    id: Optional[int]
    locus_id: int
    alias: str
    normalized_alias: str
    language: Optional[str] = None
    script: Optional[str] = None
    transliteration_scheme: Optional[str] = None
    is_primary: bool = False


@dataclass(frozen=True)
class Source:
    id: Optional[int]
    system_id: int
    short_title: str
    full_title: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[int] = None
    citation: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class Assertion:
    id: Optional[int]
    subject_locus_id: int
    relation_type_id: int
    object_locus_id: int
    source_id: int
    source_locator: Optional[str] = None
    note: Optional[str] = None
    confidence: Optional[float] = None
    variant_group: Optional[str] = None
    is_editorial: bool = False


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold().strip()
    return " ".join(text.split())


class CorrespondenceDB:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def create_system(self, slug: str, name: str, description: str | None = None) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO system (slug, name, description)
            VALUES (?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = COALESCE(excluded.description, system.description)
            RETURNING id
            """,
            (slug, name, description),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def get_system_id(self, slug: str) -> int:
        row = self.conn.execute("SELECT id FROM system WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown system slug: {slug}")
        return int(row[0])

    def create_source(
        self,
        *,
        system_slug: str,
        short_title: str,
        full_title: str | None = None,
        edition: str | None = None,
        year: int | None = None,
        citation: str | None = None,
        url: str | None = None,
    ) -> int:
        system_id = self.get_system_id(system_slug)
        cur = self.conn.execute(
            """
            INSERT INTO source (system_id, short_title, full_title, edition, year, citation, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_id, short_title, edition) DO UPDATE SET
                full_title = COALESCE(excluded.full_title, source.full_title),
                year = COALESCE(excluded.year, source.year),
                citation = COALESCE(excluded.citation, source.citation),
                url = COALESCE(excluded.url, source.url)
            RETURNING id
            """,
            (system_id, short_title, full_title, edition, year, citation, url),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def get_source_id(self, short_title: str) -> int:
        rows = self.conn.execute(
            "SELECT id, short_title, edition FROM source WHERE short_title = ? ORDER BY id",
            (short_title,),
        ).fetchall()
        if not rows:
            raise ValueError(f"Unknown source short title: {short_title}")
        if len(rows) > 1:
            editions = ", ".join(row["edition"] or "<no edition>" for row in rows)
            raise ValueError(
                f"Source title {short_title!r} is ambiguous across editions: {editions}. "
                "Use unique short titles in the prototype."
            )
        return int(rows[0]["id"])

    def create_relation_type(
        self,
        slug: str,
        forward_label: str,
        reverse_label: str | None = None,
        is_symmetric: bool = False,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO relation_type (slug, forward_label, reverse_label, is_symmetric)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                forward_label = excluded.forward_label,
                reverse_label = COALESCE(excluded.reverse_label, relation_type.reverse_label),
                is_symmetric = excluded.is_symmetric
            RETURNING id
            """,
            (slug, forward_label, reverse_label, int(is_symmetric)),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def get_relation_type_id(self, slug: str) -> int:
        row = self.conn.execute("SELECT id FROM relation_type WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown relation type slug: {slug}")
        return int(row[0])

    def create_locus(
        self,
        *,
        system_slug: str | None,
        kind: str,
        canonical_name: str,
        description: str | None = None,
        extra: dict | None = None,
    ) -> int:
        system_id = self.get_system_id(system_slug) if system_slug else None
        normalized_name = normalize(canonical_name)
        cur = self.conn.execute(
            """
            INSERT INTO locus (system_id, kind, canonical_name, normalized_name, description, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(kind, normalized_name, system_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                description = COALESCE(excluded.description, locus.description),
                extra_json = COALESCE(excluded.extra_json, locus.extra_json)
            RETURNING id
            """,
            (
                system_id,
                kind,
                canonical_name,
                normalized_name,
                description,
                json.dumps(extra, ensure_ascii=False) if extra is not None else None,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def add_alias(
        self,
        *,
        locus_name: str,
        alias: str,
        kind: str | None = None,
        system_slug: str | None = None,
        language: str | None = None,
        script: str | None = None,
        transliteration_scheme: str | None = None,
        is_primary: bool = False,
    ) -> int:
        locus_id = self.resolve_locus_id(locus_name, kind=kind, system_slug=system_slug)
        cur = self.conn.execute(
            """
            INSERT INTO alias (locus_id, alias, normalized_alias, language, script, transliteration_scheme, is_primary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(locus_id, normalized_alias) DO UPDATE SET
                alias = excluded.alias,
                language = COALESCE(excluded.language, alias.language),
                script = COALESCE(excluded.script, alias.script),
                transliteration_scheme = COALESCE(excluded.transliteration_scheme, alias.transliteration_scheme),
                is_primary = excluded.is_primary
            RETURNING id
            """,
            (
                locus_id,
                alias,
                normalize(alias),
                language,
                script,
                transliteration_scheme,
                int(is_primary),
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def lookup(self, name: str, kind: str | None = None, system_slug: str | None = None) -> list[sqlite3.Row]:
        q = normalize(name)
        params: list[object] = [q, q]
        where = ["(l.normalized_name = ? OR a.normalized_alias = ?)"]

        if kind:
            where.append("l.kind = ?")
            params.append(kind)

        if system_slug:
            where.append("sys.slug = ?")
            params.append(system_slug)

        sql = f"""
            SELECT DISTINCT
                l.id,
                l.kind,
                l.canonical_name,
                l.description,
                sys.slug AS system_slug,
                sys.name AS system_name
            FROM locus l
            LEFT JOIN alias a ON a.locus_id = l.id
            LEFT JOIN system sys ON sys.id = l.system_id
            WHERE {' AND '.join(where)}
            ORDER BY l.kind, l.canonical_name
        """
        return list(self.conn.execute(sql, params).fetchall())

    def search(self, text: str, limit: int = 20) -> list[sqlite3.Row]:
        q = f"%{normalize(text)}%"
        sql = """
            SELECT DISTINCT
                l.id,
                l.kind,
                l.canonical_name,
                sys.slug AS system_slug,
                l.description
            FROM locus l
            LEFT JOIN alias a ON a.locus_id = l.id
            LEFT JOIN system sys ON sys.id = l.system_id
            WHERE l.normalized_name LIKE ? OR a.normalized_alias LIKE ? OR COALESCE(l.description, '') LIKE ?
            ORDER BY l.kind, l.canonical_name
            LIMIT ?
        """
        return list(self.conn.execute(sql, (q, q, q, limit)).fetchall())

    def resolve_locus_id(self, name: str, kind: str | None = None, system_slug: str | None = None) -> int:
        rows = self.lookup(name, kind=kind, system_slug=system_slug)
        if not rows:
            raise ValueError(f"No locus found for {name!r}")
        if len(rows) > 1:
            rendered = "; ".join(
                f"id={row['id']} kind={row['kind']} name={row['canonical_name']} system={row['system_slug'] or '-'}"
                for row in rows
            )
            raise ValueError(f"Ambiguous locus name {name!r}: {rendered}")
        return int(rows[0]["id"])

    def create_assertion(
        self,
        *,
        subject_name: str,
        relation_slug: str,
        object_name: str,
        source_short_title: str,
        subject_kind: str | None = None,
        object_kind: str | None = None,
        subject_system: str | None = None,
        object_system: str | None = None,
        source_locator: str | None = None,
        note: str | None = None,
        confidence: float | None = None,
        variant_group: str | None = None,
        is_editorial: bool = False,
    ) -> int:
        subject_locus_id = self.resolve_locus_id(subject_name, kind=subject_kind, system_slug=subject_system)
        object_locus_id = self.resolve_locus_id(object_name, kind=object_kind, system_slug=object_system)
        relation_type_id = self.get_relation_type_id(relation_slug)
        source_id = self.get_source_id(source_short_title)

        cur = self.conn.execute(
            """
            INSERT INTO assertion (
                subject_locus_id, relation_type_id, object_locus_id, source_id,
                source_locator, note, confidence, variant_group, is_editorial
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject_locus_id, relation_type_id, object_locus_id, source_id, source_locator) DO UPDATE SET
                note = COALESCE(excluded.note, assertion.note),
                confidence = COALESCE(excluded.confidence, assertion.confidence),
                variant_group = COALESCE(excluded.variant_group, assertion.variant_group),
                is_editorial = excluded.is_editorial
            RETURNING id
            """,
            (
                subject_locus_id,
                relation_type_id,
                object_locus_id,
                source_id,
                source_locator,
                note,
                confidence,
                variant_group,
                int(is_editorial),
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def related(
        self,
        name: str,
        *,
        relation_slug: str | None = None,
        kind: str | None = None,
        system_slug: str | None = None,
    ) -> list[sqlite3.Row]:
        locus_id = self.resolve_locus_id(name, kind=kind, system_slug=system_slug)
        params: list[object] = [locus_id]
        where = ["a.subject_locus_id = ?"]
        if relation_slug:
            where.append("rt.slug = ?")
            params.append(relation_slug)

        sql = f"""
            SELECT
                rt.slug AS relation,
                rt.forward_label,
                o.kind AS object_kind,
                o.canonical_name AS object_name,
                osys.slug AS object_system,
                s.short_title AS source,
                s.edition AS source_edition,
                a.source_locator,
                a.note,
                a.confidence,
                a.variant_group,
                a.is_editorial
            FROM assertion a
            JOIN relation_type rt ON rt.id = a.relation_type_id
            JOIN locus o ON o.id = a.object_locus_id
            LEFT JOIN system osys ON osys.id = o.system_id
            JOIN source s ON s.id = a.source_id
            WHERE {' AND '.join(where)}
            ORDER BY rt.slug, o.kind, o.canonical_name, s.short_title
        """
        return list(self.conn.execute(sql, params).fetchall())

    def compare(self, name: str, system_slugs: Iterable[str], kind: str | None = None) -> dict[str, dict[str, list[str]]]:
        system_slugs = list(system_slugs)
        if not system_slugs:
            raise ValueError("At least one system slug is required for compare().")

        matches = [row for row in self.lookup(name, kind=kind) if row["system_slug"] in system_slugs]
        if not matches:
            raise ValueError(
                f"No loci named {name!r} found in the requested systems: {', '.join(system_slugs)}"
            )

        locus_ids = [int(row["id"]) for row in matches]
        params: list[object] = [*locus_ids, *system_slugs]
        locus_placeholders = ", ".join("?" for _ in locus_ids)
        system_placeholders = ", ".join("?" for _ in system_slugs)
        sql = f"""
            SELECT
                sys.slug AS system_slug,
                rt.slug AS relation_slug,
                o.canonical_name AS object_name
            FROM assertion a
            JOIN relation_type rt ON rt.id = a.relation_type_id
            JOIN source src ON src.id = a.source_id
            JOIN system sys ON sys.id = src.system_id
            JOIN locus o ON o.id = a.object_locus_id
            WHERE a.subject_locus_id IN ({locus_placeholders})
              AND sys.slug IN ({system_placeholders})
            ORDER BY rt.slug, sys.slug, o.canonical_name
        """
        rows = self.conn.execute(sql, params).fetchall()
        result: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            rel = row["relation_slug"]
            sys_slug = row["system_slug"]
            result.setdefault(rel, {}).setdefault(sys_slug, []).append(row["object_name"])
        return result

    def export_locus_json(self, name: str, kind: str | None = None, system_slug: str | None = None) -> dict:
        matches = self.lookup(name, kind=kind, system_slug=system_slug)
        if not matches:
            raise ValueError(f"No locus found for {name!r}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous locus name {name!r}; refine with --kind and/or --system")

        row = matches[0]
        locus_id = int(row["id"])
        aliases = [
            dict(alias=r["alias"], language=r["language"], script=r["script"], is_primary=bool(r["is_primary"]))
            for r in self.conn.execute(
                "SELECT alias, language, script, is_primary FROM alias WHERE locus_id = ? ORDER BY alias",
                (locus_id,),
            ).fetchall()
        ]
        assertions = [dict(r) for r in self.related(name, kind=kind, system_slug=system_slug)]
        return {
            "id": locus_id,
            "kind": row["kind"],
            "canonical_name": row["canonical_name"],
            "description": row["description"],
            "system": row["system_slug"],
            "aliases": aliases,
            "assertions": assertions,
        }

    def seed_demo(self) -> None:
        self.init_schema()

        self.create_system("crowley777", "Crowley 777", "Prototype namespace for sample correspondences")
        self.create_system("skinner", "Skinner", "Prototype namespace for sample correspondences")
        self.create_system("common", "Common", "Shared entities not tied to one symbolic namespace")

        self.create_source(
            system_slug="crowley777",
            short_title="777",
            full_title="777 and Other Qabalistic Writings",
            edition="prototype",
            citation="Minimal demo seed data for CLI testing",
        )
        self.create_source(
            system_slug="skinner",
            short_title="CMT",
            full_title="The Complete Magician's Tables",
            edition="prototype",
            citation="Minimal demo seed data for CLI testing",
        )

        self.create_relation_type("planetary_attribution", "is attributed to planet")
        self.create_relation_type("metal_of", "has metal")
        self.create_relation_type("color_of", "has color")
        self.create_relation_type("angel_of", "has angel")
        self.create_relation_type("tarot_attribution", "is attributed to tarot card")

        self.create_locus(system_slug="crowley777", kind="sephirah", canonical_name="Netzach")
        self.create_locus(system_slug="crowley777", kind="planet", canonical_name="Venus")
        self.create_locus(system_slug="crowley777", kind="metal", canonical_name="Copper")
        self.create_locus(system_slug="crowley777", kind="color", canonical_name="Emerald Green")
        self.create_locus(system_slug="crowley777", kind="angel", canonical_name="Haniel")
        self.create_locus(system_slug="crowley777", kind="tarot", canonical_name="The Empress")

        self.create_locus(system_slug="skinner", kind="planet", canonical_name="Venus")
        self.create_locus(system_slug="skinner", kind="metal", canonical_name="Copper")
        self.create_locus(system_slug="skinner", kind="color", canonical_name="Green")
        self.create_locus(system_slug="skinner", kind="angel", canonical_name="Anael")

        self.add_alias(locus_name="Netzach", alias="נצח", kind="sephirah", system_slug="crowley777", language="he", script="Hebr")
        self.add_alias(locus_name="Venus", alias="Aphrodite", kind="planet", system_slug="crowley777", language="grc")

        self.create_assertion(
            subject_name="Netzach",
            subject_kind="sephirah",
            subject_system="crowley777",
            relation_slug="planetary_attribution",
            object_name="Venus",
            object_kind="planet",
            object_system="crowley777",
            source_short_title="777",
            source_locator="Table I, row Netzach",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="crowley777",
            relation_slug="metal_of",
            object_name="Copper",
            object_kind="metal",
            object_system="crowley777",
            source_short_title="777",
            source_locator="Prototype seed row for Venus",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="crowley777",
            relation_slug="color_of",
            object_name="Emerald Green",
            object_kind="color",
            object_system="crowley777",
            source_short_title="777",
            source_locator="Prototype seed row for Venus",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="crowley777",
            relation_slug="angel_of",
            object_name="Haniel",
            object_kind="angel",
            object_system="crowley777",
            source_short_title="777",
            source_locator="Prototype seed row for Venus",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="crowley777",
            relation_slug="tarot_attribution",
            object_name="The Empress",
            object_kind="tarot",
            object_system="crowley777",
            source_short_title="777",
            source_locator="Prototype seed row for Venus",
        )

        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="skinner",
            relation_slug="metal_of",
            object_name="Copper",
            object_kind="metal",
            object_system="skinner",
            source_short_title="CMT",
            source_locator="Prototype seed row for Venus",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="skinner",
            relation_slug="color_of",
            object_name="Green",
            object_kind="color",
            object_system="skinner",
            source_short_title="CMT",
            source_locator="Prototype seed row for Venus",
        )
        self.create_assertion(
            subject_name="Venus",
            subject_kind="planet",
            subject_system="skinner",
            relation_slug="angel_of",
            object_name="Anael",
            object_kind="angel",
            object_system="skinner",
            source_short_title="CMT",
            source_locator="Prototype seed row for Venus",
        )

        self.conn.commit()


def cmd_init_db(db: CorrespondenceDB, _: argparse.Namespace) -> None:
    db.init_schema()
    print(f"Initialized schema in {db.db_path}")


def cmd_seed_demo(db: CorrespondenceDB, _: argparse.Namespace) -> None:
    db.seed_demo()
    print(f"Seeded demo data in {db.db_path}")


def cmd_add_system(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    system_id = db.create_system(args.slug, args.name, args.description)
    print(f"system_id={system_id}")


def cmd_add_source(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    source_id = db.create_source(
        system_slug=args.system,
        short_title=args.short_title,
        full_title=args.full_title,
        edition=args.edition,
        year=args.year,
        citation=args.citation,
        url=args.url,
    )
    print(f"source_id={source_id}")


def cmd_add_relation_type(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    relation_id = db.create_relation_type(
        args.slug,
        args.forward_label,
        reverse_label=args.reverse_label,
        is_symmetric=args.is_symmetric,
    )
    print(f"relation_type_id={relation_id}")


def cmd_add_locus(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    extra = json.loads(args.extra_json) if args.extra_json else None
    locus_id = db.create_locus(
        system_slug=args.system,
        kind=args.kind,
        canonical_name=args.name,
        description=args.description,
        extra=extra,
    )
    print(f"locus_id={locus_id}")


def cmd_add_alias(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    alias_id = db.add_alias(
        locus_name=args.name,
        alias=args.alias,
        kind=args.kind,
        system_slug=args.system,
        language=args.language,
        script=args.script,
        transliteration_scheme=args.transliteration_scheme,
        is_primary=args.is_primary,
    )
    print(f"alias_id={alias_id}")


def cmd_add_assertion(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    assertion_id = db.create_assertion(
        subject_name=args.subject,
        relation_slug=args.relation,
        object_name=args.object,
        source_short_title=args.source,
        subject_kind=args.subject_kind,
        object_kind=args.object_kind,
        subject_system=args.subject_system,
        object_system=args.object_system,
        source_locator=args.locator,
        note=args.note,
        confidence=args.confidence,
        variant_group=args.variant_group,
        is_editorial=args.is_editorial,
    )
    print(f"assertion_id={assertion_id}")


def cmd_lookup(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    rows = db.lookup(args.name, kind=args.kind, system_slug=args.system)
    if not rows:
        print(f"No exact match for {args.name!r}; trying partial search.", file=sys.stderr)
        rows = db.search(args.name)
    if not rows:
        raise SystemExit(1)
    for row in rows:
        system_str = row["system_slug"] or "-"
        print(f"id={row['id']}\tkind={row['kind']}\tname={row['canonical_name']}\tsystem={system_str}")


def cmd_search(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    rows = db.search(args.text, limit=args.limit)
    for row in rows:
        system_str = row["system_slug"] or "-"
        print(f"id={row['id']}\tkind={row['kind']}\tname={row['canonical_name']}\tsystem={system_str}")


def cmd_related(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    rows = db.related(args.name, relation_slug=args.relation, kind=args.kind, system_slug=args.system)
    if not rows:
        print("No related assertions found.")
        return
    for row in rows:
        print(
            f"relation={row['relation']}\t"
            f"object_kind={row['object_kind']}\t"
            f"object={row['object_name']}\t"
            f"object_system={row['object_system'] or '-'}\t"
            f"source={row['source']}\t"
            f"locator={row['source_locator'] or '-'}"
        )


def cmd_compare(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    result = db.compare(args.name, args.systems, kind=args.kind)
    if not result:
        print("No comparison rows found.")
        return

    for relation in sorted(result):
        print(f"RELATION: {relation}")
        sys_map = result[relation]
        for system_slug in args.systems:
            values = sys_map.get(system_slug, [])
            joined = ", ".join(values) if values else "<none>"
            print(f"  {system_slug}: {joined}")


def cmd_export_json(db: CorrespondenceDB, args: argparse.Namespace) -> None:
    data = db.export_locus_json(args.name, kind=args.kind, system_slug=args.system)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magi",
        description="Prototype CLI for magician's tables and correspondences.",
    )
    parser.add_argument("--db", default="magi.db", help="Path to SQLite database file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialize the SQLite schema").set_defaults(func=cmd_init_db)
    sub.add_parser("seed-demo", help="Load a small demo dataset").set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("add-system", help="Add or update a symbolic system")
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--description")
    p.set_defaults(func=cmd_add_system)

    p = sub.add_parser("add-source", help="Add or update a bibliographic source")
    p.add_argument("--system", required=True, help="System slug")
    p.add_argument("--short-title", required=True)
    p.add_argument("--full-title")
    p.add_argument("--edition")
    p.add_argument("--year", type=int)
    p.add_argument("--citation")
    p.add_argument("--url")
    p.set_defaults(func=cmd_add_source)

    p = sub.add_parser("add-relation-type", help="Add or update a relation type")
    p.add_argument("--slug", required=True)
    p.add_argument("--forward-label", required=True)
    p.add_argument("--reverse-label")
    p.add_argument("--is-symmetric", action="store_true")
    p.set_defaults(func=cmd_add_relation_type)

    p = sub.add_parser("add-locus", help="Add or update a locus")
    p.add_argument("--system", help="System slug")
    p.add_argument("--kind", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--description")
    p.add_argument("--extra-json")
    p.set_defaults(func=cmd_add_locus)

    p = sub.add_parser("add-alias", help="Add or update an alias")
    p.add_argument("--name", required=True, help="Canonical locus name")
    p.add_argument("--alias", required=True)
    p.add_argument("--kind")
    p.add_argument("--system")
    p.add_argument("--language")
    p.add_argument("--script")
    p.add_argument("--transliteration-scheme")
    p.add_argument("--is-primary", action="store_true")
    p.set_defaults(func=cmd_add_alias)

    p = sub.add_parser("add-assertion", help="Add or update an assertion")
    p.add_argument("--subject", required=True)
    p.add_argument("--relation", required=True)
    p.add_argument("--object", required=True)
    p.add_argument("--source", required=True, help="Source short title")
    p.add_argument("--subject-kind")
    p.add_argument("--object-kind")
    p.add_argument("--subject-system")
    p.add_argument("--object-system")
    p.add_argument("--locator")
    p.add_argument("--note")
    p.add_argument("--confidence", type=float)
    p.add_argument("--variant-group")
    p.add_argument("--is-editorial", action="store_true")
    p.set_defaults(func=cmd_add_assertion)

    p = sub.add_parser("lookup", help="Look up an exact locus name or alias")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("search", help="Search names, aliases, and descriptions")
    p.add_argument("text")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("related", help="Show related assertions for a locus")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.add_argument("--relation")
    p.set_defaults(func=cmd_related)

    p = sub.add_parser("compare", help="Compare a locus across systems using source system namespaces")
    p.add_argument("name")
    p.add_argument("systems", nargs="+", help="System slugs to compare, e.g. crowley777 skinner")
    p.add_argument("--kind")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("export-json", help="Export one locus and its assertions as JSON")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.set_defaults(func=cmd_export_json)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db = CorrespondenceDB(args.db)
    try:
        args.func(db, args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
