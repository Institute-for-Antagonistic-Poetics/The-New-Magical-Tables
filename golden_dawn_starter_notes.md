# Golden Dawn / Crowley 777 Starter CSV

This companion note describes how the CSV was assembled.

## Scope

The CSV is a **starter dataset** for the schema used by `magi_build.py`. It focuses on a single internally coherent family of correspondences:

- Golden Dawn style Tree of Life correspondences
- Crowley 777-style path/sephirah usage
- practical element tables
- a small number of clearly marked editorial planet rollups for direct lookup convenience

## What is included

- 10 sephiroth with meanings, numbers, colors, divine names, archangels, angelic choirs, perfumes/scents, planetary or analogous attributions, metals where present, stones, plants, symbols, tarot groupings, and Greek/Roman deity rows
- 22 paths with Hebrew letters, Major Arcana attributions, colors, astrological attributions, plants, stones, scents, and tools
- 4 classical elements with divine names, archangels, elemental kings, elemental beings, and directions
- 7 direct planet lookup profiles marked `is_editorial=true`

## Editorial handling

The rows where `subject_kind=planet` are **editorial rollups**, not verbatim rows from a single source table.
They were projected from the associated sephirah in the same Golden Dawn lineage so that the software can do direct
planet lookups without requiring the user to infer everything through the sephirah first.

Examples:
- Binah -> Saturn yields an editorial Saturn profile
- Netzach -> Venus yields an editorial Venus profile
- Yesod -> Moon yields an editorial Moon profile

These rows are marked with:
- `is_editorial=true`
- a note explaining the derivation
- slightly lower confidence than direct chart rows

## Spelling policy

Most values follow the source pages closely. A few obvious source spellings or OCR-like forms were preserved with `[sic]`
and, where straightforward, a normalized form was placed in `object_aliases`.

Examples:
- `Preperations [sic]` with alias `Preparations`
- `Woormwood [sic]` with alias `Wormwood`
- `Cocanut [sic]` with alias `Coconut`

One uncertain item was preserved as `Snowpop [sic]` rather than silently normalizing it.

## Sources used

1. Samuel Scarborough, *The Tree of Life: Filing Cabinet of the Western Mystery Tradition and Methods to Recall the Information*  
   https://hermetic.com/jwmt/v1n3/treeoflife

2. Colin Low, *Malkuth*  
   https://hermetic.com/caduceus/qabalah/041_kab

3. *Planetary hours*  
   https://en.wikipedia.org/wiki/Planetary_hours

4. *Yesod (יסוד) - Foundation*  
   https://archetypes.kaabalah.com/sphere/yesod

## Validation status

The CSV was checked locally against the currently documented schema requirements from the uploaded markdown files:
- all required columns are present
- all required columns are non-blank in every data row

The actual `magi_build.py` validator was not run because that script was not among the uploaded files.
