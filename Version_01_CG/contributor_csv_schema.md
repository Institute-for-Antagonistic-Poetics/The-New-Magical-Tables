# Contributor CSV schema

This document describes the CSV format consumed by `magi_build.py`.

The CSV is a **long-form assertion table**. Each row expresses one correspondence assertion plus the metadata needed to place it in a system and source.

## Conceptual model

A row states:

- which symbolic system the row belongs to,
- which source supports it,
- what the subject locus is,
- what relation is asserted,
- what the object locus is,
- and optional provenance, alias, and editorial metadata.

Example assertion:

```text
Netzach -> planetary_attribution -> Venus
```

## Required columns

These columns must exist in the CSV header and must be non-blank in every data row.

| Column | Meaning | Example |
|---|---|---|
| `system_slug` | slug for the source system namespace attached to the row and source record | `crowley777` |
| `system_name` | human-readable name for `system_slug` | `Crowley 777` |
| `source_short_title` | short source identifier | `777` |
| `subject_name` | canonical subject name for this row | `Venus` |
| `subject_kind` | subject class | `planet` |
| `relation_slug` | machine-readable relation key | `color_of` |
| `relation_label` | human-readable label for the relation | `Color` |
| `object_name` | canonical object name for this row | `Emerald Green` |
| `object_kind` | object class | `color` |

## Optional columns

These columns are optional, but many are useful and some are strongly recommended.

| Column | Meaning | Example |
|---|---|---|
| `system_description` | optional description for the system | `Golden Dawn style correspondences as represented in Crowley 777` |
| `source_full_title` | full title of the source | `777 and Other Qabalistic Writings` |
| `source_edition` | edition or transcription label | `Weiser 1986` |
| `source_year` | source year as an integer | `1986` |
| `source_citation` | freeform citation text | `Crowley, Aleister. 777 and Other Qabalistic Writings.` |
| `source_url` | optional URL for the source | `https://example.org/777` |
| `subject_system_slug` | override namespace for the subject locus; defaults to `system_slug` | `crowley777` |
| `object_system_slug` | override namespace for the object locus; defaults to `system_slug` | `skinner` |
| `subject_description` | optional description for the subject locus | `Seventh sephirah on the Tree of Life` |
| `object_description` | optional description for the object locus | `A strong green used in the Venus scale` |
| `subject_aliases` | aliases for the subject locus, separated by `|` or `;` | `Aphrodite|Kypris` |
| `object_aliases` | aliases for the object locus, separated by `|` or `;` | `Rose Pink;Verdant Green` |
| `source_locator` | citation locator inside the source | `Table I, row Netzach` |
| `note` | editorial or interpretive note on the assertion | `Commonly inherited via planetary attribution` |
| `confidence` | numeric confidence score | `0.8` |
| `variant_group` | label for a variant set or editorial grouping | `gd_main` |
| `is_editorial` | boolean-like value for editorial assertions | `true` |

## Aliases

`subject_aliases` and `object_aliases` are split on either `|` or `;`.

Accepted examples:

```text
Aphrodite|Kypris
Netzach;Victory
נצח
```

Avoid commas for alias separation unless you deliberately want the comma inside a single alias value.

## Boolean handling

`is_editorial` is treated as true when normalized to one of:

- `1`
- `true`
- `yes`
- `y`

Anything else is treated as false.

Examples:

```text
true
yes
1
```

## Numeric handling

`source_year` is parsed as an integer.

`confidence` is parsed as a floating-point number.

Examples:

```text
1986
0.75
1.0
```

Leave the field blank if the value is unknown.

## Normalization behavior

The importer normalizes values for comparison and deduplication by:

- Unicode NFKC normalization
- lowercasing with `casefold()`
- trimming outer whitespace
- collapsing internal whitespace runs to one space

This affects matching, deduplication, and alias resolution.

## System and source behavior

### `system_slug` and `system_name`

The importer creates or updates a system row from these columns.

### `subject_system_slug` and `object_system_slug`

If omitted, the importer defaults them to `system_slug`.

Use these when the source system and the locus namespace should differ.

Example use case:
- the source record is attached to a row collected under one editorial namespace,
- but the subject or object locus should live in a different namespace.

## Relation behavior

`relation_slug` is the canonical machine key used in the database.

`relation_label` is the human-readable label stored for display.

Recommended style:

- slug: lowercase, underscore-separated
- label: title case or a short readable noun phrase

Examples:

| Slug | Label |
|---|---|
| `planetary_attribution` | `Planet` |
| `color_of` | `Color` |
| `metal_of` | `Metal` |
| `angel_of` | `Angel` |
| `tarot_attribution` | `Tarot` |

## Suggested `kind` values

The importer does not currently enforce an enum, but these values align with the current CLI behavior and demo data:

- `sephirah`
- `planet`
- `color`
- `metal`
- `angel`
- `deity`
- `perfume`
- `stone`
- `day`
- `number`
- `plant`
- `tarot`

You can add other kinds, but the practitioner-facing CLI will only render especially nicely for relation and kind families it already recognizes.

## Minimal valid row

```csv
system_slug,system_name,source_short_title,subject_name,subject_kind,relation_slug,relation_label,object_name,object_kind
crowley777,Crowley 777,777,Venus,planet,color_of,Color,Emerald Green,color
```

## Recommended practical row

```csv
system_slug,system_name,source_short_title,source_full_title,source_edition,subject_name,subject_kind,subject_aliases,relation_slug,relation_label,object_name,object_kind,source_locator,note
crowley777,Crowley 777,777,777 and Other Qabalistic Writings,prototype,Venus,planet,Aphrodite,color_of,Color,Emerald Green,color,Prototype row for Venus,Venus color in the prototype dataset
```

## Example multi-row snippet

```csv
system_slug,system_name,source_short_title,source_full_title,source_edition,subject_name,subject_kind,subject_aliases,relation_slug,relation_label,object_name,object_kind,object_aliases,source_locator
crowley777,Crowley 777,777,777 and Other Qabalistic Writings,prototype,Netzach,sephirah,נצח,planetary_attribution,Planet,Venus,planet,Aphrodite,Table I, row Netzach
crowley777,Crowley 777,777,777 and Other Qabalistic Writings,prototype,Venus,planet,Aphrodite,color_of,Color,Emerald Green,color,,Prototype row for Venus
crowley777,Crowley 777,777,777 and Other Qabalistic Writings,prototype,Venus,planet,Aphrodite,metal_of,Metal,Copper,metal,,Prototype row for Venus
```

## Validation rules currently enforced

`magi_build.py validate-csv` currently checks:

- CSV has a header row
- all required columns exist
- all required columns are non-blank in every data row

It does not yet enforce:

- allowed relation slugs
- allowed kinds
- numeric ranges for `confidence`
- citation style
- alias language/script metadata
- source consistency across files

Those are reasonable future improvements.

## Merge behavior

`merge-csv` supports two dedupe modes.

### `assertion` mode

This is the default. It compares:

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

Use this when multiple contributor files may repeat the same assertion with slightly different incidental metadata.

### `full` mode

This compares every column in the row.

Use this when editorial notes and non-key metadata should also participate in deduplication.

## Building the database

Validate first:

```bash
python magi_build.py validate-csv your_data.csv
```

Then build:

```bash
python magi_build.py build-db your_data.csv --db magi.db --replace
```

Build from several files:

```bash
python magi_build.py build-db part1.csv part2.csv part3.csv --db magi.db --replace
```

## Demo dataset

The included `demo_correspondences.csv` is a compact example that builds successfully and supports the current CLI features.
