import csv
import sys
import unicodedata

class MgcTblLinter:
    def __init__(self):
        # Canonical mapping of entities to expected Unicode glyphs
        self.VALID_GLYPHS = {
            "Saturn": "♄", "Jupiter": "♃", "Mars": "♂", "Sun": "☉", 
            "Venus": "♀", "Mercury": "☿", "Moon": "☽",
            "Fire": "🜂", "Water": "🜄", "Air": "🜁", "Earth": "🜃",
            "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋", 
            "Leo": "♌", "Virgo": "♍", "Libra": "♎", "Scorpio": "♏", 
            "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓"
        }
        self.REQUIRED_COLS = {'entity', 'glyph', 'category', 'value', 'system_name'}
        self.errors = []
        self.warnings = []

    def lint(self, filename):
        print(f"[*] Auditing {filename}...")
        try:
            with open(filename, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Check Header Integrity
                if not self.REQUIRED_COLS.issubset(set(reader.fieldnames)):
                    missing = self.REQUIRED_COLS - set(reader.fieldnames)
                    self.errors.append(f"CRITICAL: Missing columns {missing}")
                    return False

                for line_num, row in enumerate(reader, start=2):
                    self._check_row(row, line_num)

            self._report()
            return len(self.errors) == 0

        except FileNotFoundError:
            print(f"Error: File '{filename}' not found.")
            return False

    def _check_row(self, row, line_num):
        entity = row.get('entity', '').strip()
        glyph = row.get('glyph', '').strip()
        category = row.get('category', '').strip()
        value = row.get('value', '').strip()

        # 1. Check for empty critical fields
        if not entity or not value:
            self.errors.append(f"Line {line_num}: Entity or Value is empty.")

        # 2. Validate Glyphs (Unicode-Aware)
        if entity in self.VALID_GLYPHS:
            expected = self.VALID_GLYPHS[entity]
            if glyph != expected:
                self.warnings.append(
                    f"Line {line_num}: Glyph mismatch for {entity}. Expected '{expected}', found '{glyph}'."
                )
        
        # 3. Check for obvious misspellings in Categories
        canonical_categories = ["Color", "Metal", "Stone", "Incense", "Day", "Number"]
        if category and category not in canonical_categories:
            # We treat this as a warning because users might have custom categories
            self.warnings.append(f"Line {line_num}: Unknown category '{category}'.")

    def _report(self):
        print("-" * 40)
        if not self.errors and not self.warnings:
            print("✨ All clear! Data is resonant.")
        else:
            for err in self.errors:
                print(f"[ERROR] {err}")
            for warn in self.warnings:
                print(f"[WARN]  {warn}")
        print("-" * 40)
        print(f"Audit Complete: {len(self.errors)} errors, {len(self.warnings)} warnings.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mgctbl_linter.py <file.csv>")
    else:
        linter = MgcTblLinter()
        linter.lint(sys.argv[1])