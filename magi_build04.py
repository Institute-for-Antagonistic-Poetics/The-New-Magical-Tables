
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

APP_NAME = "magi"
APP_AUTHOR = "TurnerLab"
DEFAULT_DB_FILENAME = "magi.db"

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

REQUIRED_COLUMNS = [
    "system_slug",
    "system_name",
    "source_short_title",
    "subject_name",
    "subject_kind",
    "relation_slug",
    "relation_label",
    "object_name",
    "object_kind",
]

OPTIONAL_COLUMNS = [
    "system_description",
    "source_full_title",
    "source_edition",
    "source_year",
    "source_citation",
    "source_url",
    "subject_system_slug",
    "object_system_slug",
    "subject_description",
    "object_description",
    "subject_aliases",
    "object_aliases",
    "source_locator",
    "note",
    "confidence",
    "variant_group",
    "is_editorial",
]

PREFERRED_FIELD_ORDER = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

DEMO_ROWS = [
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Netzach",
        "subject_kind": "sephirah",
        "subject_aliases": "נצח",
        "relation_slug": "planetary_attribution",
        "relation_label": "Planet",
        "object_name": "Venus",
        "object_kind": "planet",
        "source_locator": "Table I, row Netzach",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "subject_aliases": "Aphrodite",
        "relation_slug": "color_of",
        "relation_label": "Color",
        "object_name": "Emerald Green",
        "object_kind": "color",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "metal_of",
        "relation_label": "Metal",
        "object_name": "Copper",
        "object_kind": "metal",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "angel_of",
        "relation_label": "Angel",
        "object_name": "Haniel",
        "object_kind": "angel",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "deity_of",
        "relation_label": "Deity",
        "object_name": "Aphrodite",
        "object_kind": "deity",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "perfume_of",
        "relation_label": "Perfume",
        "object_name": "Rose",
        "object_kind": "perfume",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "stone_of",
        "relation_label": "Stone",
        "object_name": "Emerald",
        "object_kind": "stone",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "day_of",
        "relation_label": "Day",
        "object_name": "Friday",
        "object_kind": "day",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "number_of",
        "relation_label": "Number",
        "object_name": "7",
        "object_kind": "number",
        "source_locator": "Prototype row for Venus",
    },
    {
        "system_slug": "crowley777",
        "system_name": "Crowley 777",
        "source_short_title": "777",
        "source_full_title": "777 and Other Qabalistic Writings",
        "source_edition": "prototype",
        "subject_name": "Venus",
        "subject_kind": "planet",
        "relation_slug": "plant_of",
        "relation_label": "Plant",
        "object_name": "Myrtle",
        "object_kind": "plant",
        "source_locator": "Prototype row for Venus",
    },
]

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.casefold().strip()
    return " ".join(text.split())

def humanize_slug(slug: str) -> str:
    return re.sub(r"[_\-]+", " ", slug or "").strip().title()

def split_aliases(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[|;]", value)
    return [p.strip() for p in parts if p.strip()]

def truthy(value: str | None) -> bool:
    return normalize(value or "") in {"1", "true", "yes", "y"}

def default_db_path() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(home / "AppData" / "Local")
        return Path(base) / APP_AUTHOR / APP_NAME / DEFAULT_DB_FILENAME
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME / DEFAULT_DB_FILENAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME / DEFAULT_DB_FILENAME
    return home / ".local" / "share" / APP_NAME / DEFAULT_DB_FILENAME

class DBBuilder:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def create_relation_type(self, slug: str, forward_label: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO relation_type (slug, forward_label)
            VALUES (?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                forward_label = excluded.forward_label
            RETURNING id
            """,
            (slug, forward_label),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def get_relation_type_id(self, slug: str) -> int:
        row = self.conn.execute("SELECT id FROM relation_type WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown relation slug: {slug}")
        return int(row[0])

    def create_locus(
        self,
        *,
        system_slug: str | None,
        kind: str,
        canonical_name: str,
        description: str | None = None,
    ) -> int:
        system_id = self.get_system_id(system_slug) if system_slug else None
        cur = self.conn.execute(
            """
            INSERT INTO locus (system_id, kind, canonical_name, normalized_name, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(kind, normalized_name, system_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                description = COALESCE(excluded.description, locus.description)
            RETURNING id
            """,
            (system_id, kind, canonical_name, normalize(canonical_name), description),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def resolve_locus_id(self, name: str, kind: str, system_slug: str | None) -> int:
        system_id = self.get_system_id(system_slug) if system_slug else None
        row = self.conn.execute(
            """
            SELECT id
            FROM locus
            WHERE normalized_name = ? AND kind = ? AND system_id IS ?
            """,
            (normalize(name), kind, system_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown locus: {name!r} ({kind}, {system_slug})")
        return int(row[0])

    def add_alias(self, *, locus_id: int, alias: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO alias (locus_id, alias, normalized_alias)
            VALUES (?, ?, ?)
            ON CONFLICT(locus_id, normalized_alias) DO UPDATE SET alias = excluded.alias
            RETURNING id
            """,
            (locus_id, alias, normalize(alias)),
        )
        row = cur.fetchone()
        self.conn.commit()
        return int(row[0])

    def create_assertion(
        self,
        *,
        subject_locus_id: int,
        relation_slug: str,
        object_locus_id: int,
        source_id: int,
        source_locator: str | None = None,
        note: str | None = None,
        confidence: float | None = None,
        variant_group: str | None = None,
        is_editorial: bool = False,
    ) -> int:
        relation_type_id = self.get_relation_type_id(relation_slug)
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

    def import_row(self, row: dict[str, str]) -> None:
        system_slug = row["system_slug"].strip()
        system_name = row["system_name"].strip()
        system_description = (row.get("system_description") or "").strip() or None
        subject_system_slug = (row.get("subject_system_slug") or "").strip() or system_slug
        object_system_slug = (row.get("object_system_slug") or "").strip() or system_slug
        source_short_title = row["source_short_title"].strip()
        source_full_title = (row.get("source_full_title") or "").strip() or None
        source_edition = (row.get("source_edition") or "").strip() or None
        source_year_raw = (row.get("source_year") or "").strip()
        source_year = int(source_year_raw) if source_year_raw else None
        source_citation = (row.get("source_citation") or "").strip() or None
        source_url = (row.get("source_url") or "").strip() or None

        subject_name = row["subject_name"].strip()
        subject_kind = row["subject_kind"].strip()
        subject_description = (row.get("subject_description") or "").strip() or None

        relation_slug = row["relation_slug"].strip()
        relation_label = row["relation_label"].strip() or humanize_slug(relation_slug)

        object_name = row["object_name"].strip()
        object_kind = row["object_kind"].strip()
        object_description = (row.get("object_description") or "").strip() or None

        source_locator = (row.get("source_locator") or "").strip() or None
        note = (row.get("note") or "").strip() or None
        confidence_raw = (row.get("confidence") or "").strip()
        confidence = float(confidence_raw) if confidence_raw else None
        variant_group = (row.get("variant_group") or "").strip() or None
        is_editorial = truthy(row.get("is_editorial"))

        self.create_system(system_slug, system_name, system_description)
        if subject_system_slug != system_slug:
            self.create_system(subject_system_slug, humanize_slug(subject_system_slug))
        if object_system_slug != system_slug:
            self.create_system(object_system_slug, humanize_slug(object_system_slug))

        source_id = self.create_source(
            system_slug=system_slug,
            short_title=source_short_title,
            full_title=source_full_title,
            edition=source_edition,
            year=source_year,
            citation=source_citation,
            url=source_url,
        )
        self.create_relation_type(relation_slug, relation_label)

        subject_id = self.create_locus(
            system_slug=subject_system_slug,
            kind=subject_kind,
            canonical_name=subject_name,
            description=subject_description,
        )
        object_id = self.create_locus(
            system_slug=object_system_slug,
            kind=object_kind,
            canonical_name=object_name,
            description=object_description,
        )

        for alias in split_aliases(row.get("subject_aliases")):
            self.add_alias(locus_id=subject_id, alias=alias)
        for alias in split_aliases(row.get("object_aliases")):
            self.add_alias(locus_id=object_id, alias=alias)

        self.create_assertion(
            subject_locus_id=subject_id,
            relation_slug=relation_slug,
            object_locus_id=object_id,
            source_id=source_id,
            source_locator=source_locator,
            note=note,
            confidence=confidence,
            variant_group=variant_group,
            is_editorial=is_editorial,
        )

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: missing CSV header row")
        rows = []
        for row in reader:
            rows.append({k: (v or "") for k, v in row.items()})
        return rows

def validate_rows(rows: list[dict[str, str]], *, path: Path) -> list[str]:
    errors: list[str] = []
    if not rows:
        return errors
    available = set(rows[0].keys())
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in available]
    if missing_cols:
        errors.append(f"{path}: missing required columns: {', '.join(missing_cols)}")
        return errors
    for idx, row in enumerate(rows, start=2):
        for col in REQUIRED_COLUMNS:
            if not (row.get(col) or "").strip():
                errors.append(f"{path}: row {idx}: blank required value in column {col}")
    return errors

def merge_key(row: dict[str, str], mode: str) -> tuple[str, ...]:
    if mode == "full":
        keys = sorted(row.keys())
    else:
        keys = [
            "system_slug",
            "source_short_title",
            "source_locator",
            "subject_system_slug",
            "subject_name",
            "subject_kind",
            "relation_slug",
            "object_system_slug",
            "object_name",
            "object_kind",
        ]
    return tuple(normalize(row.get(k, "")) for k in keys)

def union_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    fields = set()
    for row in rows:
        fields.update(row.keys())
    ordered = [f for f in PREFERRED_FIELD_ORDER if f in fields]
    remainder = sorted(fields - set(ordered))
    return ordered + remainder

def cmd_show_schema(args: argparse.Namespace) -> int:
    print("Required CSV columns:")
    for col in REQUIRED_COLUMNS:
        print(f"  - {col}")
    print("\nOptional CSV columns:")
    for col in OPTIONAL_COLUMNS:
        print(f"  - {col}")
    return 0

def cmd_write_template(args: argparse.Namespace) -> int:
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = DEMO_ROWS if args.demo else [{col: "" for col in PREFERRED_FIELD_ORDER}]
    fieldnames = union_fieldnames(rows)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote template CSV to {path}")
    return 0

def cmd_validate_csv(args: argparse.Namespace) -> int:
    all_errors: list[str] = []
    for name in args.inputs:
        path = Path(name)
        try:
            rows = read_csv_rows(path)
            all_errors.extend(validate_rows(rows, path=path))
        except Exception as exc:
            all_errors.append(f"{path}: {exc}")
    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        return 1
    print("All CSV files passed basic validation.")
    return 0

def cmd_merge_csv(args: argparse.Namespace) -> int:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    all_errors: list[str] = []
    for name in args.inputs:
        path = Path(name)
        try:
            rows = read_csv_rows(path)
            errs = validate_rows(rows, path=path)
            if errs:
                all_errors.extend(errs)
                continue
            for row in rows:
                key = merge_key(row, args.dedupe)
                if key not in seen:
                    seen.add(key)
                    merged.append(row)
        except Exception as exc:
            all_errors.append(f"{path}: {exc}")
    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = union_fieldnames(merged)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)
    print(f"Wrote merged CSV with {len(merged)} rows to {out}")
    return 0

def cmd_build_db(args: argparse.Namespace) -> int:
    db_path = Path(args.db or default_db_path())
    if args.replace and db_path.exists():
        db_path.unlink()
    builder = DBBuilder(db_path)
    try:
        builder.init_schema()
        imported = 0
        for name in args.inputs:
            path = Path(name)
            rows = read_csv_rows(path)
            errs = validate_rows(rows, path=path)
            if errs:
                for err in errs:
                    print(err, file=sys.stderr)
                return 1
            for row in rows:
                builder.import_row(row)
                imported += 1
    finally:
        builder.close()
    print(f"Imported {imported} CSV rows into {db_path}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magi-build",
        description="Build and maintain the correspondence database from contributor CSV files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show-schema", help="Print the expected CSV schema").set_defaults(func=cmd_show_schema)

    p = sub.add_parser("write-template", help="Write a blank or demo CSV template")
    p.add_argument("output")
    p.add_argument("--demo", action="store_true", help="write a small demo dataset instead of a blank template")
    p.set_defaults(func=cmd_write_template)

    p = sub.add_parser("validate-csv", help="Validate one or more CSV files")
    p.add_argument("inputs", nargs="+")
    p.set_defaults(func=cmd_validate_csv)

    p = sub.add_parser("merge-csv", help="Merge multiple CSV files into one deduplicated CSV")
    p.add_argument("output")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--dedupe", choices=["assertion", "full"], default="assertion")
    p.set_defaults(func=cmd_merge_csv)

    p = sub.add_parser("build-db", help="Build or update a SQLite database from one or more CSV files")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--db", help=f"database path (default: {default_db_path()})")
    p.add_argument("--replace", action="store_true", help="replace the database file before importing")
    p.set_defaults(func=cmd_build_db)

    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))

if __name__ == "__main__":
    raise SystemExit(main())
