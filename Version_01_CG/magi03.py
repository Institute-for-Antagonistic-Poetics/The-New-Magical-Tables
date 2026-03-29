
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAVE_RICH = True
except Exception:
    HAVE_RICH = False


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

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "red": "\033[31m",
}

DISPLAY_RELATIONS = {
    "planetary_attribution": "Planet",
    "metal_of": "Metal",
    "color_of": "Color",
    "angel_of": "Angel",
    "tarot_attribution": "Tarot",
    "deity_of": "Deity",
    "perfume_of": "Perfume",
    "stone_of": "Stone",
    "day_of": "Day",
    "number_of": "Number",
    "plant_of": "Plant",
}

SECTION_MAP = {
    "planetary_attribution": "Core",
    "day_of": "Core",
    "number_of": "Core",
    "deity_of": "Names and Powers",
    "angel_of": "Names and Powers",
    "metal_of": "Materials",
    "stone_of": "Materials",
    "plant_of": "Materials",
    "perfume_of": "Materials",
    "color_of": "Visual Symbols",
    "tarot_attribution": "Visual Symbols",
}

SECTION_ORDER = [
    "Core",
    "Names and Powers",
    "Materials",
    "Visual Symbols",
    "Source Trail",
]

GOAL_RULES = {
    "love": {
        "summary": "attraction, harmony, affection, beauty, friendship, reconciliation",
        "default_focus": "Venus",
        "default_kind": "planet",
        "default_system": "crowley777",
        "preferred_form": "talisman",
    },
    "purification": {
        "summary": "washing, clarification, cooling, reflection, dream work, ritual cleansing",
        "default_focus": "Moon",
        "default_kind": "planet",
        "default_system": "crowley777",
        "preferred_form": "rite",
    },
    "protection": {
        "summary": "defense, warding, courage, force, cutting through hostile influence",
        "default_focus": "Mars",
        "default_kind": "planet",
        "default_system": "crowley777",
        "preferred_form": "talisman",
    },
    "prosperity": {
        "summary": "growth, patronage, beneficence, expansion, lawful success",
        "default_focus": "Jupiter",
        "default_kind": "planet",
        "default_system": "crowley777",
        "preferred_form": "rite",
    },
}


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
                "Use unique short titles in this prototype."
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
                sys.slug AS system_slug
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
                l.description,
                sys.slug AS system_slug
            FROM locus l
            LEFT JOIN alias a ON a.locus_id = l.id
            LEFT JOIN system sys ON sys.id = l.system_id
            WHERE l.normalized_name LIKE ? OR a.normalized_alias LIKE ? OR COALESCE(l.description, '') LIKE ?
            ORDER BY l.kind, l.canonical_name
            LIMIT ?
        """
        return list(self.conn.execute(sql, (q, q, q, limit)).fetchall())

    def resolve_locus(self, name: str, kind: str | None = None, system_slug: str | None = None) -> sqlite3.Row:
        rows = self.lookup(name, kind=kind, system_slug=system_slug)
        if not rows:
            raise ValueError(f"No locus found for {name!r}")
        if len(rows) > 1:
            rendered = "; ".join(
                f"id={row['id']} kind={row['kind']} name={row['canonical_name']} system={row['system_slug'] or '-'}"
                for row in rows
            )
            raise ValueError(f"Ambiguous locus name {name!r}: {rendered}")
        return rows[0]

    def resolve_locus_id(self, name: str, kind: str | None = None, system_slug: str | None = None) -> int:
        return int(self.resolve_locus(name, kind=kind, system_slug=system_slug)["id"])

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

    def related_rows(self, locus_id: int, relation_slug: str | None = None) -> list[sqlite3.Row]:
        params: list[object] = [locus_id]
        where = ["a.subject_locus_id = ?"]
        if relation_slug:
            where.append("rt.slug = ?")
            params.append(relation_slug)
        sql = f"""
            SELECT
                a.id,
                rt.slug AS relation,
                o.id AS object_id,
                o.kind AS object_kind,
                o.canonical_name AS object_name,
                osys.slug AS object_system,
                s.short_title AS source,
                a.source_locator,
                a.note,
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

    def related(self, name: str, relation_slug: str | None = None, kind: str | None = None, system_slug: str | None = None) -> list[sqlite3.Row]:
        locus_id = self.resolve_locus_id(name, kind=kind, system_slug=system_slug)
        return self.related_rows(locus_id, relation_slug=relation_slug)

    def aliases_for(self, locus_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT alias FROM alias WHERE locus_id = ? ORDER BY is_primary DESC, alias",
            (locus_id,),
        ).fetchall()
        return [row["alias"] for row in rows]

    def compare(self, name: str, system_slugs: list[str], kind: str | None = None) -> dict[str, dict[str, list[str]]]:
        if not system_slugs:
            raise ValueError("At least one system slug is required.")
        matches = [row for row in self.lookup(name, kind=kind) if row["system_slug"] in system_slugs]
        if not matches:
            raise ValueError(f"No loci named {name!r} found in the requested systems: {', '.join(system_slugs)}")

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
        out: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            out.setdefault(row["relation_slug"], {}).setdefault(row["system_slug"], []).append(row["object_name"])
        return out

    def export_locus_json(self, name: str, kind: str | None = None, system_slug: str | None = None) -> dict:
        locus = self.resolve_locus(name, kind=kind, system_slug=system_slug)
        locus_id = int(locus["id"])
        return {
            "id": locus_id,
            "kind": locus["kind"],
            "canonical_name": locus["canonical_name"],
            "description": locus["description"],
            "system": locus["system_slug"],
            "aliases": self.aliases_for(locus_id),
            "assertions": [dict(r) for r in self.related_rows(locus_id)],
        }

    def _collect_values(self, grouped: dict[str, list[dict]], label: str) -> list[str]:
        values = []
        for section in grouped.values():
            for item in section:
                if item["label"] == label:
                    values.append(item["value"])
        return values

    def build_working_profile(self, name: str, kind: str | None = None, system_slug: str | None = None) -> dict:
        locus = self.resolve_locus(name, kind=kind, system_slug=system_slug)
        locus_id = int(locus["id"])
        direct_rows = self.related_rows(locus_id)
        grouped: dict[str, list[dict]] = {section: [] for section in SECTION_ORDER}
        seen: set[tuple] = set()

        planetary_targets = [row for row in direct_rows if row["relation"] == "planetary_attribution"]

        def add_rows(rows: list[sqlite3.Row], inherited_from: str | None = None) -> None:
            for r in rows:
                section = SECTION_MAP.get(r["relation"], "Source Trail")
                key = (section, r["relation"], r["object_name"], r["source"], inherited_from)
                if key in seen:
                    continue
                seen.add(key)
                grouped.setdefault(section, []).append(
                    {
                        "relation": r["relation"],
                        "label": DISPLAY_RELATIONS.get(r["relation"], r["relation"]),
                        "value": r["object_name"],
                        "source": r["source"],
                        "locator": r["source_locator"],
                        "note": r["note"],
                        "inherited_from": inherited_from,
                    }
                )

        add_rows(direct_rows, inherited_from=None)
        for row in planetary_targets:
            inherited = [r for r in self.related_rows(int(row["object_id"])) if r["relation"] != "planetary_attribution"]
            add_rows(inherited, inherited_from=row["object_name"])

        aliases = self.aliases_for(locus_id)
        suggestions = self.make_practitioner_suggestions(locus["canonical_name"], grouped)
        return {
            "locus": dict(locus),
            "aliases": aliases,
            "grouped": grouped,
            "suggestions": suggestions,
        }

    def make_practitioner_suggestions(self, title: str, grouped: dict[str, list[dict]]) -> dict[str, list[str]]:
        planets = self._collect_values(grouped, "Planet")
        colors = self._collect_values(grouped, "Color")
        metals = self._collect_values(grouped, "Metal")
        stones = self._collect_values(grouped, "Stone")
        perfumes = self._collect_values(grouped, "Perfume")
        plants = self._collect_values(grouped, "Plant")
        angels = self._collect_values(grouped, "Angel")
        deities = self._collect_values(grouped, "Deity")
        tarot = self._collect_values(grouped, "Tarot")
        days = self._collect_values(grouped, "Day")
        numbers = self._collect_values(grouped, "Number")

        brief = []
        if planets:
            brief.append(f"Work primarily in the field of {', '.join(planets)}.")
        if days:
            brief.append(f"Prefer timing on {', '.join(days)}.")
        if colors:
            brief.append(f"Use a dominant palette of {', '.join(colors)}.")
        if metals or stones:
            brief.append(f"Choose base materials such as {', '.join(metals + stones)}.")
        if angels or deities:
            brief.append(f"Primary names or powers to invoke: {', '.join(angels + deities)}.")
        if tarot:
            brief.append(f"Supporting image or emblem: {', '.join(tarot)}.")

        talisman = []
        if metals:
            talisman.append(f"Base metal: {metals[0]}")
        elif stones:
            talisman.append(f"Base stone: {stones[0]}")
        if colors:
            talisman.append(f"Dominant color: {colors[0]}")
        if numbers:
            talisman.append(f"Use {numbers[0]} as a structuring number for repetitions, divisions, or marks")
        if angels:
            talisman.append(f"Primary name for inscription or prayer: {angels[0]}")
        elif deities:
            talisman.append(f"Primary divine name for inscription or prayer: {deities[0]}")
        if perfumes:
            talisman.append(f"Fumigation: {perfumes[0]}")
        if plants:
            talisman.append(f"Add a sympathetic plant: {plants[0]}")
        if tarot:
            talisman.append(f"Supporting emblem: {tarot[0]}")

        ritual = []
        if brief:
            ritual.extend(brief)
        else:
            ritual.append(f"Use {title} as the main symbolic focus and refine with additional correspondences.")
        if perfumes:
            ritual.append(f"Incense or scent support: {', '.join(perfumes)}.")
        if plants:
            ritual.append(f"Botanical support: {', '.join(plants)}.")

        return {"brief": brief, "talisman": talisman, "ritual": ritual}

    def resolve_goal(self, goal: str) -> tuple[str, dict]:
        q = normalize(goal)
        for key, spec in GOAL_RULES.items():
            if q == normalize(key):
                return key, spec
        raise ValueError(f"Unknown goal {goal!r}. Try one of: {', '.join(sorted(GOAL_RULES))}")

    def build_operation_plan(
        self,
        goal: str,
        *,
        form: str | None = None,
        focus_name: str | None = None,
        focus_kind: str | None = None,
        system_slug: str | None = None,
    ) -> dict:
        goal_key, goal_spec = self.resolve_goal(goal)
        chosen_form = form or goal_spec["preferred_form"]
        chosen_system = system_slug or goal_spec["default_system"]
        chosen_focus = focus_name or goal_spec["default_focus"]
        chosen_kind = focus_kind or goal_spec["default_kind"]

        profile = self.build_working_profile(chosen_focus, kind=chosen_kind, system_slug=chosen_system)
        grouped = profile["grouped"]

        def vals(label: str) -> list[str]:
            return self._collect_values(grouped, label)

        planets = vals("Planet")
        days = vals("Day")
        colors = vals("Color")
        metals = vals("Metal")
        stones = vals("Stone")
        perfumes = vals("Perfume")
        plants = vals("Plant")
        angels = vals("Angel")
        deities = vals("Deity")
        tarot = vals("Tarot")
        numbers = vals("Number")

        summary = [
            f"Goal: {goal_key} — {goal_spec['summary']}.",
            f"Symbolic center: {profile['locus']['canonical_name']} in {profile['locus']['system_slug']}.",
        ]
        if planets:
            summary.append(f"Primary current or ruler: {', '.join(planets)}.")
        if days:
            summary.append(f"Favorable timing: {', '.join(days)}.")
        if colors:
            summary.append(f"Visual key: {', '.join(colors)}.")
        if angels or deities:
            summary.append(f"Main names or powers: {', '.join(angels + deities)}.")

        materials = []
        if metals:
            materials.append(f"Metal: {', '.join(metals)}")
        if stones:
            materials.append(f"Stone: {', '.join(stones)}")
        if perfumes:
            materials.append(f"Perfume: {', '.join(perfumes)}")
        if plants:
            materials.append(f"Plant: {', '.join(plants)}")
        if colors:
            materials.append(f"Color palette: {', '.join(colors)}")
        if tarot:
            materials.append(f"Image or emblem: {', '.join(tarot)}")

        steps = []
        if chosen_form == "talisman":
            steps.append("Choose the physical base from the listed metal or stone.")
            if colors:
                steps.append(f"Make the dominant visual field {colors[0]}.")
            if tarot:
                steps.append(f"Use {tarot[0]} or another corresponding emblem as the main image.")
            if angels:
                steps.append(f"Write or recite {angels[0]} as the principal operative name.")
            elif deities:
                steps.append(f"Write or recite {deities[0]} as the principal divine name.")
            if numbers:
                steps.append(f"Use {numbers[0]} as a structuring number in marks, repetitions, or divisions.")
            if perfumes:
                steps.append(f"Fumigate the completed talisman with {perfumes[0]}.")
            if days:
                steps.append(f"Consecrate or charge it on {days[0]}.")
        elif chosen_form == "rite":
            steps.append("Set the visual field with the listed colors, symbols, and names.")
            if plants:
                steps.append(f"Place or wear {plants[0]} as a sympathetic material.")
            if perfumes:
                steps.append(f"Open the rite with {perfumes[0]} as the main scent or incense.")
            if angels:
                steps.append(f"Invoke {angels[0]} as the principal operative name.")
            elif deities:
                steps.append(f"Invoke {deities[0]} as the principal divine name.")
            if tarot:
                steps.append(f"Keep {tarot[0]} visible as the emblematic image during the rite.")
            if days:
                steps.append(f"Perform the rite preferably on {days[0]}.")
        elif chosen_form == "altar-kit":
            if colors:
                steps.append(f"Use {colors[0]} as the altar cloth or dominant background.")
            if metals:
                steps.append(f"Use {metals[0]} for the main vessel, disk, or ornament if practical.")
            if perfumes:
                steps.append(f"Keep {perfumes[0]} as the primary incense or oil.")
            if plants:
                steps.append(f"Add {plants[0]} as a living or dried botanical token.")
            if angels:
                steps.append(f"Place the name {angels[0]} where the eye naturally returns.")
            elif deities:
                steps.append(f"Place the name {deities[0]} where the eye naturally returns.")
        else:
            raise ValueError("Unknown form. Use talisman, rite, or altar-kit.")

        cautions = [
            "Treat this as a compositional aid, not a substitute for source checking.",
            "When you import real tables, prefer explicit provenance for every assertion shown here.",
        ]

        return {
            "goal": goal_key,
            "form": chosen_form,
            "focus": profile["locus"]["canonical_name"],
            "system": profile["locus"]["system_slug"],
            "profile": profile,
            "summary": summary,
            "materials": materials,
            "steps": steps,
            "cautions": cautions,
        }

    def seed_demo(self) -> None:
        self.init_schema()
        self.create_system("crowley777", "Crowley 777", "Prototype namespace for sample correspondences")
        self.create_system("skinner", "Skinner", "Prototype namespace for sample correspondences")

        self.create_source(system_slug="crowley777", short_title="777", full_title="777 and Other Qabalistic Writings", edition="prototype")
        self.create_source(system_slug="skinner", short_title="CMT", full_title="The Complete Magician's Tables", edition="prototype")

        for slug, label in [
            ("planetary_attribution", "is attributed to planet"),
            ("metal_of", "has metal"),
            ("color_of", "has color"),
            ("angel_of", "has angel"),
            ("tarot_attribution", "is attributed to tarot card"),
            ("deity_of", "has deity"),
            ("perfume_of", "has perfume"),
            ("stone_of", "has stone"),
            ("day_of", "has day"),
            ("number_of", "has number"),
            ("plant_of", "has plant"),
        ]:
            self.create_relation_type(slug, label)

        crowley_data = {
            "Venus": {
                "color": "Emerald Green",
                "metal": "Copper",
                "angel": "Haniel",
                "tarot": "The Empress",
                "deity": "Aphrodite",
                "perfume": "Rose",
                "stone": "Emerald",
                "day": "Friday",
                "number": "7",
                "plant": "Myrtle",
            },
            "Moon": {
                "color": "White",
                "metal": "Silver",
                "angel": "Gabriel",
                "tarot": "The High Priestess",
                "deity": "Selene",
                "perfume": "Jasmine",
                "stone": "Pearl",
                "day": "Monday",
                "number": "9",
                "plant": "Willow",
            },
            "Mars": {
                "color": "Red",
                "metal": "Iron",
                "angel": "Kamael",
                "tarot": "The Tower",
                "deity": "Ares",
                "perfume": "Dragon's Blood",
                "stone": "Ruby",
                "day": "Tuesday",
                "number": "5",
                "plant": "Nettle",
            },
            "Jupiter": {
                "color": "Blue",
                "metal": "Tin",
                "angel": "Sachiel",
                "tarot": "Wheel of Fortune",
                "deity": "Zeus",
                "perfume": "Cedar",
                "stone": "Amethyst",
                "day": "Thursday",
                "number": "4",
                "plant": "Oak",
            },
        }

        for planet, attrs in crowley_data.items():
            self.create_locus(system_slug="crowley777", kind="planet", canonical_name=planet)
            for kind, value in [
                ("color", attrs["color"]),
                ("metal", attrs["metal"]),
                ("angel", attrs["angel"]),
                ("tarot", attrs["tarot"]),
                ("deity", attrs["deity"]),
                ("perfume", attrs["perfume"]),
                ("stone", attrs["stone"]),
                ("day", attrs["day"]),
                ("number", attrs["number"]),
                ("plant", attrs["plant"]),
            ]:
                self.create_locus(system_slug="crowley777", kind=kind, canonical_name=value)

        self.create_locus(system_slug="crowley777", kind="sephirah", canonical_name="Netzach")
        self.add_alias(locus_name="Netzach", alias="נצח", kind="sephirah", system_slug="crowley777", language="he", script="Hebr")
        self.add_alias(locus_name="Venus", alias="Aphrodite", kind="planet", system_slug="crowley777", language="grc")

        self.create_assertion(
            subject_name="Netzach", subject_kind="sephirah", subject_system="crowley777",
            relation_slug="planetary_attribution", object_name="Venus", object_kind="planet",
            object_system="crowley777", source_short_title="777", source_locator="Table I, row Netzach"
        )

        relation_map = {
            "metal_of": "metal",
            "color_of": "color",
            "angel_of": "angel",
            "tarot_attribution": "tarot",
            "deity_of": "deity",
            "perfume_of": "perfume",
            "stone_of": "stone",
            "day_of": "day",
            "number_of": "number",
            "plant_of": "plant",
        }

        for planet, attrs in crowley_data.items():
            for rel, kind in relation_map.items():
                key = kind
                self.create_assertion(
                    subject_name=planet, subject_kind="planet", subject_system="crowley777",
                    relation_slug=rel, object_name=attrs[key], object_kind=kind, object_system="crowley777",
                    source_short_title="777", source_locator=f"Prototype row for {planet}"
                )

        skinner_data = {
            "Venus": {"color": "Green", "metal": "Copper", "angel": "Anael", "deity": "Astarte", "perfume": "Rose", "stone": "Emerald", "day": "Friday", "number": "7"},
            "Moon": {"color": "White", "metal": "Silver", "angel": "Gabriel", "deity": "Artemis", "perfume": "Jasmine", "stone": "Pearl", "day": "Monday", "number": "9"},
        }
        for planet, attrs in skinner_data.items():
            self.create_locus(system_slug="skinner", kind="planet", canonical_name=planet)
            for kind, value in attrs.items():
                kind_name = "deity" if kind == "deity" else kind
                self.create_locus(system_slug="skinner", kind=kind_name, canonical_name=value)
            for rel, key in [("color_of", "color"), ("metal_of", "metal"), ("angel_of", "angel"), ("deity_of", "deity"), ("perfume_of", "perfume"), ("stone_of", "stone"), ("day_of", "day"), ("number_of", "number")]:
                kind_name = "deity" if key == "deity" else key
                self.create_assertion(
                    subject_name=planet, subject_kind="planet", subject_system="skinner",
                    relation_slug=rel, object_name=attrs[key], object_kind=kind_name, object_system="skinner",
                    source_short_title="CMT", source_locator=f"Prototype row for {planet}"
                )
        self.conn.commit()


class TerminalRenderer:
    def __init__(self) -> None:
        self.rich = Console() if HAVE_RICH else None

    def print_error(self, message: str) -> None:
        if HAVE_RICH:
            self.rich.print(f"[bold red]Error:[/bold red] {message}")
        else:
            print(f"{ANSI['red']}{ANSI['bold']}Error:{ANSI['reset']} {message}", file=sys.stderr)

    def _plain_block(self, title: str, lines: list[str]) -> None:
        if not lines:
            return
        print(f"\n{ANSI['bold']}{ANSI['green']}{title}{ANSI['reset']}")
        for line in lines:
            print(f"  • {line}")

    def _rich_block(self, title: str, lines: list[str], style: str = "green") -> None:
        if not lines:
            return
        self.rich.print(Panel("\n".join(f"• {line}" for line in lines), title=title, border_style=style))

    def print_lookup(self, rows: list[sqlite3.Row]) -> None:
        if HAVE_RICH:
            table = Table(title="Matches", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="dim")
            table.add_column("Kind", style="cyan")
            table.add_column("Name", style="bold")
            table.add_column("System", style="green")
            for row in rows:
                table.add_row(str(row["id"]), row["kind"], row["canonical_name"], row["system_slug"] or "—")
            self.rich.print(table)
        else:
            print(f"{ANSI['bold']}{ANSI['magenta']}Matches{ANSI['reset']}")
            for row in rows:
                print(f"  {ANSI['cyan']}{row['kind']:<12}{ANSI['reset']} {row['canonical_name']}  {ANSI['dim']}[{row['system_slug'] or '-'}]{ANSI['reset']}")

    def print_related(self, locus_name: str, rows: list[sqlite3.Row]) -> None:
        if HAVE_RICH:
            table = Table(title=f"Correspondences for {locus_name}", show_header=True, header_style="bold magenta")
            table.add_column("Type", style="cyan")
            table.add_column("Value", style="bold")
            table.add_column("Source", style="green")
            table.add_column("Locator", style="dim")
            for row in rows:
                table.add_row(DISPLAY_RELATIONS.get(row["relation"], row["relation"]), row["object_name"], row["source"], row["source_locator"] or "—")
            self.rich.print(table)
        else:
            print(f"{ANSI['bold']}{ANSI['magenta']}Correspondences for {locus_name}{ANSI['reset']}")
            for row in rows:
                label = DISPLAY_RELATIONS.get(row["relation"], row["relation"])
                print(f"  {ANSI['cyan']}{label:<12}{ANSI['reset']} {row['object_name']}  {ANSI['dim']}[{row['source']} | {row['source_locator'] or '-'}]{ANSI['reset']}")

    def print_compare(self, name: str, systems: list[str], result: dict[str, dict[str, list[str]]]) -> None:
        if HAVE_RICH:
            table = Table(title=f"Comparison for {name}", show_header=True, header_style="bold magenta")
            table.add_column("Correspondence", style="cyan")
            for system in systems:
                table.add_column(system, style="green")
            for relation in sorted(result):
                row = [DISPLAY_RELATIONS.get(relation, relation)]
                mapping = result[relation]
                for system in systems:
                    row.append(", ".join(mapping.get(system, [])) or "—")
                table.add_row(*row)
            self.rich.print(table)
        else:
            print(f"{ANSI['bold']}{ANSI['magenta']}Comparison for {name}{ANSI['reset']}")
            for relation in sorted(result):
                print(f"{ANSI['cyan']}{DISPLAY_RELATIONS.get(relation, relation)}{ANSI['reset']}")
                for system in systems:
                    print(f"  {system:<12} {', '.join(result[relation].get(system, [])) or '—'}")

    def print_profile(self, profile: dict, mode: str = "profile") -> None:
        locus = profile["locus"]
        aliases = profile["aliases"]
        grouped = profile["grouped"]
        suggestions = profile["suggestions"]

        subtitle = f"{locus['kind']} in {locus['system_slug'] or 'unspecified system'}"
        alias_line = f"Aliases: {', '.join(aliases)}" if aliases else "Aliases: none recorded"
        description = locus["description"] or ""

        if HAVE_RICH:
            title = Text()
            title.append(locus["canonical_name"], style="bold magenta")
            title.append("  ")
            title.append(subtitle, style="cyan")
            body = description + ("\n\n" if description else "") + alias_line
            self.rich.print(Panel.fit(body, title=title, border_style="magenta"))

            if mode == "profile":
                self._rich_block("Working Summary", suggestions["brief"])
            elif mode == "ritual-kit":
                self._rich_block("Ritual Use", suggestions["ritual"])
            elif mode == "talisman":
                self._rich_block("Talisman Notes", suggestions["talisman"])

            for section in SECTION_ORDER:
                items = grouped.get(section, [])
                if not items:
                    continue
                table = Table(title=section, show_header=True, header_style="bold green")
                table.add_column("Type", style="cyan", no_wrap=True)
                table.add_column("Value", style="bold")
                table.add_column("Use", style="yellow")
                table.add_column("Source", style="dim")
                for item in items:
                    use = "direct" if not item["inherited_from"] else f"via {item['inherited_from']}"
                    src = item["source"] + (f" · {item['locator']}" if item["locator"] else "")
                    table.add_row(item["label"], item["value"], use, src)
                self.rich.print(table)
        else:
            line = "═" * 72
            print(f"{ANSI['magenta']}{line}{ANSI['reset']}")
            print(f"{ANSI['bold']}{ANSI['magenta']}{locus['canonical_name']}{ANSI['reset']}  {ANSI['cyan']}{subtitle}{ANSI['reset']}")
            if description:
                print(description)
            print(f"{ANSI['dim']}{alias_line}{ANSI['reset']}")
            if mode == "profile":
                self._plain_block("Working Summary", suggestions["brief"])
            elif mode == "ritual-kit":
                self._plain_block("Ritual Use", suggestions["ritual"])
            elif mode == "talisman":
                self._plain_block("Talisman Notes", suggestions["talisman"])
            for section in SECTION_ORDER:
                items = grouped.get(section, [])
                if not items:
                    continue
                print(f"\n{ANSI['bold']}{ANSI['green']}{section}{ANSI['reset']}")
                for item in items:
                    use = "direct" if not item["inherited_from"] else f"via {item['inherited_from']}"
                    src = item["source"] + (f" · {item['locator']}" if item["locator"] else "")
                    print(f"  {ANSI['cyan']}{item['label']:<12}{ANSI['reset']} {item['value']:<20} {ANSI['yellow']}{use:<12}{ANSI['reset']} {ANSI['dim']}{src}{ANSI['reset']}")

    def print_goals(self) -> None:
        lines = [f"{key}: {spec['summary']} (default focus {spec['default_focus']}, default form {spec['preferred_form']})" for key, spec in sorted(GOAL_RULES.items())]
        if HAVE_RICH:
            self._rich_block("Available working goals", lines, style="blue")
        else:
            self._plain_block("Available working goals", lines)

    def print_operation_plan(self, plan: dict) -> None:
        title_text = f"{plan['goal'].title()} working"
        subtitle = f"{plan['form']} via {plan['focus']} [{plan['system']}]"
        if HAVE_RICH:
            title = Text()
            title.append(title_text, style="bold magenta")
            title.append("  ")
            title.append(subtitle, style="cyan")
            self.rich.print(Panel.fit("\n".join(plan["summary"]), title=title, border_style="magenta"))
            self._rich_block("Recommended materials and symbols", plan["materials"], style="green")
            self._rich_block("Procedure outline", [f"{i+1}. {step}" for i, step in enumerate(plan["steps"])], style="yellow")
            self._rich_block("Cautions", plan["cautions"], style="red")
            self.print_profile(plan["profile"], mode="talisman" if plan["form"] == "talisman" else "ritual-kit")
        else:
            print(f"{ANSI['magenta']}{'═' * 72}{ANSI['reset']}")
            print(f"{ANSI['bold']}{ANSI['magenta']}{title_text}{ANSI['reset']}  {ANSI['cyan']}{subtitle}{ANSI['reset']}")
            self._plain_block("Summary", plan["summary"])
            self._plain_block("Recommended materials and symbols", plan["materials"])
            self._plain_block("Procedure outline", [f"{i+1}. {step}" for i, step in enumerate(plan["steps"])])
            self._plain_block("Cautions", plan["cautions"])
            self.print_profile(plan["profile"], mode="talisman" if plan["form"] == "talisman" else "ritual-kit")


def cmd_init_db(db: CorrespondenceDB, renderer: TerminalRenderer, _: argparse.Namespace) -> None:
    db.init_schema()
    print(f"Initialized schema in {db.db_path}")


def cmd_seed_demo(db: CorrespondenceDB, renderer: TerminalRenderer, _: argparse.Namespace) -> None:
    db.seed_demo()
    print(f"Seeded demo data in {db.db_path}")


def cmd_add_system(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(f"system_id={db.create_system(args.slug, args.name, args.description)}")


def cmd_add_source(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(f"source_id={db.create_source(system_slug=args.system, short_title=args.short_title, full_title=args.full_title, edition=args.edition, year=args.year, citation=args.citation, url=args.url)}")


def cmd_add_relation_type(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(f"relation_type_id={db.create_relation_type(args.slug, args.forward_label, reverse_label=args.reverse_label, is_symmetric=args.is_symmetric)}")


def cmd_add_locus(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    extra = json.loads(args.extra_json) if args.extra_json else None
    print(f"locus_id={db.create_locus(system_slug=args.system, kind=args.kind, canonical_name=args.name, description=args.description, extra=extra)}")


def cmd_add_alias(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(f"alias_id={db.add_alias(locus_name=args.name, alias=args.alias, kind=args.kind, system_slug=args.system, language=args.language, script=args.script, transliteration_scheme=args.transliteration_scheme, is_primary=args.is_primary)}")


def cmd_add_assertion(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(f"assertion_id={db.create_assertion(subject_name=args.subject, relation_slug=args.relation, object_name=args.object, source_short_title=args.source, subject_kind=args.subject_kind, object_kind=args.object_kind, subject_system=args.subject_system, object_system=args.object_system, source_locator=args.locator, note=args.note, confidence=args.confidence, variant_group=args.variant_group, is_editorial=args.is_editorial)}")


def cmd_lookup(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    rows = db.lookup(args.name, kind=args.kind, system_slug=args.system)
    if not rows:
        rows = db.search(args.name)
    if not rows:
        raise ValueError(f"No results found for {args.name!r}")
    renderer.print_lookup(rows)


def cmd_search(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    rows = db.search(args.text, limit=args.limit)
    if not rows:
        raise ValueError(f"No results found for {args.text!r}")
    renderer.print_lookup(rows)


def cmd_related(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    rows = db.related(args.name, relation_slug=args.relation, kind=args.kind, system_slug=args.system)
    if not rows:
        raise ValueError("No related assertions found.")
    renderer.print_related(args.name, rows)


def cmd_profile(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    renderer.print_profile(db.build_working_profile(args.name, kind=args.kind, system_slug=args.system), mode="profile")


def cmd_ritual_kit(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    renderer.print_profile(db.build_working_profile(args.name, kind=args.kind, system_slug=args.system), mode="ritual-kit")


def cmd_talisman(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    renderer.print_profile(db.build_working_profile(args.name, kind=args.kind, system_slug=args.system), mode="talisman")


def cmd_list_goals(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    renderer.print_goals()


def cmd_working(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    plan = db.build_operation_plan(
        args.goal,
        form=args.form,
        focus_name=args.focus,
        focus_kind=args.kind,
        system_slug=args.system,
    )
    renderer.print_operation_plan(plan)


def cmd_compare(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    result = db.compare(args.name, args.systems, kind=args.kind)
    if not result:
        raise ValueError("No comparison rows found.")
    renderer.print_compare(args.name, args.systems, result)


def cmd_export_json(db: CorrespondenceDB, renderer: TerminalRenderer, args: argparse.Namespace) -> None:
    print(json.dumps(db.export_locus_json(args.name, kind=args.kind, system_slug=args.system), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magi", description="Practitioner-oriented CLI for magical correspondences.")
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
    p.add_argument("--system", required=True)
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
    p.add_argument("--system")
    p.add_argument("--kind", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--description")
    p.add_argument("--extra-json")
    p.set_defaults(func=cmd_add_locus)

    p = sub.add_parser("add-alias", help="Add or update an alias")
    p.add_argument("--name", required=True)
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
    p.add_argument("--source", required=True)
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

    p = sub.add_parser("related", help="Show direct correspondences for a locus")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.add_argument("--relation")
    p.set_defaults(func=cmd_related)

    p = sub.add_parser("profile", help="Show a practitioner-friendly working profile")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("ritual-kit", help="Show a ritual-oriented working kit")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.set_defaults(func=cmd_ritual_kit)

    p = sub.add_parser("talisman", help="Show talisman-building suggestions")
    p.add_argument("name")
    p.add_argument("--kind")
    p.add_argument("--system")
    p.set_defaults(func=cmd_talisman)

    sub.add_parser("list-goals", help="List prototype operation goals").set_defaults(func=cmd_list_goals)

    p = sub.add_parser("working", help="Compose an operation plan from a goal and optional focus")
    p.add_argument("goal", help="e.g. love, purification, protection, prosperity")
    p.add_argument("--form", choices=["talisman", "rite", "altar-kit"])
    p.add_argument("--focus", help="override the default symbolic center")
    p.add_argument("--kind", help="kind of the focus locus, e.g. planet or sephirah")
    p.add_argument("--system", help="system slug, defaults from the goal rule")
    p.set_defaults(func=cmd_working)

    p = sub.add_parser("compare", help="Compare correspondences across systems")
    p.add_argument("name")
    p.add_argument("systems", nargs="+")
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
    renderer = TerminalRenderer()
    try:
        args.func(db, renderer, args)
    except ValueError as exc:
        renderer.print_error(str(exc))
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
