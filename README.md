# Magi: contributor CSV workflow and end-user CLI

This project is split into two programs:

- `magi_build.py`: contributor and maintainer tool for working with flat files and building the SQLite database.
- `magi_cli.py`: practitioner-facing CLI that reads the database and presents ritual, talisman, and comparison views.

Most users should only need `magi_cli.py`. Contributors and maintainers will use `magi_build.py` to validate, merge, and import CSV files.

## Files in this package

- `magi_build.py`
- `magi_cli.py`
- `README.md`
- `contributor_csv_schema.md`
- `demo_correspondences.csv`
- `demo_magi.db`

## Quick start

### 1. Build a database from a CSV

```bash
python magi_build.py validate-csv demo_correspondences.csv
python magi_build.py build-db demo_correspondences.csv --db demo_magi.db --replace
```

### 2. Use the practitioner CLI

```bash
python magi_cli.py --db demo_magi.db lookup Venus
python magi_cli.py --db demo_magi.db profile Netzach --kind sephirah --system crowley777
python magi_cli.py --db demo_magi.db ritual-kit Venus --kind planet --system crowley777
python magi_cli.py --db demo_magi.db talisman Venus --kind planet --system crowley777
python magi_cli.py --db demo_magi.db working love
python magi_cli.py --db demo_magi.db compare Venus crowley777 skinner --kind planet
```

## Default database behavior

`magi_cli.py` and `magi_build.py` both accept `--db`. If `--db` is omitted, they use an OS-appropriate default database path.

You can see what the CLI will use with:

```bash
python magi_cli.py where-db
```

Current default locations are:

- Linux: `$XDG_DATA_HOME/magi/magi.db` or `~/.local/share/magi/magi.db`
- macOS: `~/Library/Application Support/magi/magi.db`
- Windows: `%LOCALAPPDATA%/TurnerLab/magi/magi.db`

For development and testing, continuing to use `--db` is the simplest approach.

## Contributor workflow

A typical contributor workflow is:

### Start from a template

Blank template:

```bash
python magi_build.py write-template my_sheet.csv
```

Demo template:

```bash
python magi_build.py write-template my_demo.csv --demo
```

### Validate one or more CSVs

```bash
python magi_build.py validate-csv part1.csv part2.csv
```

### Merge CSVs for editorial work

Deduplicate by assertion identity:

```bash
python magi_build.py merge-csv merged.csv part1.csv part2.csv
```

Deduplicate by the full row:

```bash
python magi_build.py merge-csv merged.csv part1.csv part2.csv --dedupe full
```

### Build or update a database

```bash
python magi_build.py build-db merged.csv --db magi.db --replace
```

Import multiple CSVs into one database:

```bash
python magi_build.py build-db source_a.csv source_b.csv source_c.csv --db magi.db --replace
```

## Builder commands

### Show the CSV schema

```bash
python magi_build.py show-schema
```

### Write a blank or demo template

```bash
python magi_build.py write-template output.csv
python magi_build.py write-template output.csv --demo
```

### Validate CSV files

```bash
python magi_build.py validate-csv file1.csv file2.csv
```

### Merge CSV files

```bash
python magi_build.py merge-csv merged.csv file1.csv file2.csv
python magi_build.py merge-csv merged.csv file1.csv file2.csv --dedupe full
```

### Build a SQLite database

```bash
python magi_build.py build-db file1.csv file2.csv --db magi.db --replace
```

## CLI commands

### Database path

```bash
python magi_cli.py where-db
python magi_cli.py --db demo_magi.db where-db
```

### Lookups and search

```bash
python magi_cli.py --db demo_magi.db lookup Venus
python magi_cli.py --db demo_magi.db lookup נצח
python magi_cli.py --db demo_magi.db search green
```

### Direct correspondences

```bash
python magi_cli.py --db demo_magi.db related Venus --kind planet --system crowley777
python magi_cli.py --db demo_magi.db related Netzach --kind sephirah --system crowley777
```

### Practitioner-facing views

```bash
python magi_cli.py --db demo_magi.db profile Netzach --kind sephirah --system crowley777
python magi_cli.py --db demo_magi.db ritual-kit Venus --kind planet --system crowley777
python magi_cli.py --db demo_magi.db talisman Venus --kind planet --system crowley777
```

### Goal-driven operation plans

Show the available prototype goals:

```bash
python magi_cli.py --db demo_magi.db list-goals
```

Use a default symbolic center for the goal:

```bash
python magi_cli.py --db demo_magi.db working love
python magi_cli.py --db demo_magi.db working purification --form rite
python magi_cli.py --db demo_magi.db working prosperity --form altar-kit
```

Override the symbolic center:

```bash
python magi_cli.py --db demo_magi.db working protection --focus Mars --kind planet --system crowley777
```

### Compare systems

```bash
python magi_cli.py --db demo_magi.db compare Venus crowley777 skinner --kind planet
```

### Export JSON

```bash
python magi_cli.py --db demo_magi.db export-json Venus --kind planet --system crowley777
```

## How the CSV import model works

The importer expects a **long-form assertion table**: one CSV row per correspondence assertion.

Examples:

- `Netzach -> planetary_attribution -> Venus`
- `Venus -> color_of -> Emerald Green`
- `Venus -> angel_of -> Haniel`

This format is intentionally simple for contributors:

- one row = one claim,
- repeated metadata is allowed,
- multiple CSVs can be merged,
- aliases can be supplied inline,
- provenance can be tracked per assertion.

## Important column behavior

### Required columns

These must be present and non-empty in every row:

- `system_slug`
- `system_name`
- `source_short_title`
- `subject_name`
- `subject_kind`
- `relation_slug`
- `relation_label`
- `object_name`
- `object_kind`

### Optional but strongly recommended columns

These are especially useful in practice:

- `source_full_title`
- `source_edition`
- `source_locator`
- `subject_aliases`
- `object_aliases`
- `note`
- `confidence`
- `variant_group`
- `is_editorial`

## Alias format

Aliases are split on `|` or `;`.

Examples:

```text
Aphrodite|Kypris
נצח
Netzach;Victory
```

Do not use commas for aliases if you want them preserved as a single field without additional CSV quoting complexity.

## Deduplication behavior in `merge-csv`

Default mode:

```bash
--dedupe assertion
```

This treats rows as duplicates when these fields match after normalization:

- `system_slug`
- `source_short_title`
- `source_locator`
- `subject_system_slug`
- `subject_name`
- `subject_kind`
- `relation_slug`
- `object_system_slug`
- `object_name`
- `object_kind`

Full-row mode:

```bash
--dedupe full
```

This only treats rows as duplicates when all columns match after normalization.

## What the demo data contains

The included `demo_correspondences.csv` is intentionally small but usable. It contains:

- a Crowley-style `Netzach -> Venus` attribution
- a Venus working set in `crowley777`
- a smaller comparison set for `Venus` and `Moon` in `skinner`

That is enough to test:

- lookup and alias resolution
- inherited correspondences through `planetary_attribution`
- practitioner-oriented profile and talisman output
- cross-system comparison for at least one planet

## Suggested next step for contributors

Once this structure is stable, the next useful editorial improvement is to standardize:

- permitted `kind` values
- permitted `relation_slug` values
- transliteration conventions
- citation and locator style
- how uncertain or disputed attributions are represented

The companion file `contributor_csv_schema.md` gives a column-by-column schema and examples.
