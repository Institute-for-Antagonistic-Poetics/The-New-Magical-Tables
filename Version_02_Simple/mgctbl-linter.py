import csv
import sys
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Initialize Rich Console for beautiful output
console = Console()

class MgcTblLinter:
    def __init__(self):
        # Expanded Unicode Dictionary for Occult Practice
        self.VALID_GLYPHS = {
            # Planets (Classical + Outer)
            "Saturn": "♄", "Jupiter": "♃", "Mars": "♂", "Sun": "☉", 
            "Venus": "♀", "Mercury": "☿", "Moon": "☽",
            "Uranus": "♅", "Neptune": "♆", "Pluto": "♇",
            
            # The Four Elements
            "Fire": "🜂", "Water": "🜄", "Air": "🜁", "Earth": "🜃",
            "Spirit": "🜀",
            
            # The Alchemical Primes (The Tria Prima)
            "Sulfur": "🜍", "Salt": "🜔", "Mercury_Alchemical": "🜏",
            
            # Zodiac
            "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋", 
            "Leo": "♌", "Virgo": "♍", "Libra": "♎", "Scorpio": "♏", 
            "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓",

            # Other Common Symbols
            "Pentagram": "⛤", "Ankh": "☥", "Wheel of Hecate": "⚝"
        }
        self.REQUIRED_COLS = {'entity', 'glyph', 'category', 'value', 'system_name'}
        self.issues = []

    def lint(self, filename, verbose=False):
        console.print(Panel(f"[bold magenta]Starting Ritual Audit:[/bold magenta] {filename}", expand=False))
        
        try:
            with open(filename, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Verify Header
                actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                if not self.REQUIRED_COLS.issubset(actual_cols):
                    missing = self.REQUIRED_COLS - actual_cols
                    console.print(f"[bold red]Critical Error:[/bold red] Missing columns: {missing}")
                    return

                for line_num, row in enumerate(reader, start=2):
                    self._check_row(row, line_num)

            self._display_report()

        except Exception as e:
            console.print(f"[bold red]System Error:[/bold red] {str(e)}")

    def _check_row(self, row, line_num):
            entity = row.get('entity', '').strip()
            glyph = row.get('glyph', '').strip()
            category = row.get('category', '').strip()
            value = row.get('value', '').strip()

            # 1. Validate Glyphs (Unicode-Aware)
            if entity in self.VALID_GLYPHS:
                expected = self.VALID_GLYPHS[entity]
                if glyph != expected:
                    self.issues.append({
                        "line": line_num,
                        "level": "Warning",
                        "msg": f"Glyph mismatch for [cyan]{entity}[/cyan]. Expected '{expected}', found '{glyph}'."
                    })
            
            # 2. Validate Categories (The missing piece!)
            # We use a list of standard occult categories.
            # Users can still use custom ones, but the linter will flag them for review.
            canonical_categories = [
                "Color", "Metal", "Stone", "Incense", "Day", 
                "Number", "Angel", "Intelligence", "Spirit", "Sign"
            ]
            if category and category not in canonical_categories:
                self.issues.append({
                    "line": line_num,
                    "level": "Warning",
                    "msg": f"Unknown category '[yellow]{category}[/yellow]'. (Not in canonical list)"
                })

            # 3. Check for empty critical fields
            if not entity or not value:
                self.issues.append({
                    "line": line_num, 
                    "level": "Error", 
                    "msg": "[bold red]Critical:[/bold red] Empty entity or value field."
                })
    def _display_report(self):
        if not self.issues:
            console.print("\n[bold green]✨ Data is harmonized. No dissonance detected.[/bold green]\n")
            return

        table = Table(title="Audit Results", show_header=True, header_style="bold cyan")
        table.add_column("Line", style="dim", width=6)
        table.add_column("Level", width=12)
        table.add_column("Message")

        for issue in self.issues:
            level_style = "bold red" if issue['level'] == "Error" else "bold yellow"
            table.add_row(
                str(issue['line']), 
                Text(issue['level'], style=level_style), 
                issue['msg']
            )

        console.print(table)
        console.print(f"\n[bold]Total Issues Found:[/bold] {len(self.issues)}\n")

def main():
    parser = argparse.ArgumentParser(
        description="""
🔮 mgctbl-sync Linter
Ensures your magical correspondence CSV files are syntactically and symbolically correct 
before they are merged into the primary database.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example Usage:
  python mgctbl_sync.py check my_ritual_data.csv
  
Note: Ensure your CSV is encoded in UTF-8 to support magical glyphs (♂, ♄, ♈).
        """
    )

    parser.add_argument("command", choices=["check"], help="Action to perform (currently only 'check' is supported)")
    parser.add_argument("file", help="The .csv file containing magical facts")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed processing steps")

    args = parser.parse_args()

    if args.command == "check":
        linter = MgcTblLinter()
        linter.lint(args.file, verbose=args.verbose)

if __name__ == "__main__":
    main()