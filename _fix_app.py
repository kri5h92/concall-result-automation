"""Script to clean up dead code from app.py and fix the positions-based label split."""
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# --- Step 1: Find and remove the dead code block ---
# The dead block starts at the first (shadowed) _format_item definition
# and ends just before _format_quote_blocks.
dead_start = content.find('\ndef _format_item(text: str) -> str:\n    """Bold descriptor label before')
# The end of the dead block is just before def _format_quote_blocks
dead_end = content.find('\ndef _format_quote_blocks(text: str) -> str:')

print(f"Dead block: chars {dead_start} to {dead_end}")
print(f"Dead block preview (start): {repr(content[dead_start:dead_start+80])}")
print(f"Dead block preview (end): {repr(content[dead_end-20:dead_end+50])}")

if dead_start == -1 or dead_end == -1:
    print("ERROR: Could not find block boundaries!")
else:
    # Remove the dead block (replace with empty string)
    content = content[:dead_start] + content[dead_end:]
    print("Dead code removed.")

# --- Step 2: Fix the positions-based split in _parse_items_safe ---
old_positions = '''    positions = [
        match.start()
        for match in _re.finditer(
            r"(?<!^)(?<!\\w)(?=(?:[A-Z][A-Za-z0-9/&\'()%-]{1,20}(?: [A-Za-z0-9/&\'()%-]{1,20}){0,4}):\\s)",
            text,
        )
    ]
    if positions:
        parts = []
        start = 0
        for pos in positions:
            part = text[start:pos].strip()
            if part:
                parts.append(part)
            start = pos
        last = text[start:].strip()
        if last:
            parts.append(last)
        if len(parts) > 1:
            return parts'''

new_positions = '''    positions = [
        m.end(1)
        for m in _re.finditer(
            r"([.!?][\'\\\"\\u2019]?\\s+)(?=[A-Z][A-Za-z0-9/&\'()%-]{1,25}(?:\\s[A-Za-z0-9/&\'()%-]{1,25}){0,7}:\\s)",
            text,
        )
    ]
    if positions:
        parts = []
        start = 0
        for pos in positions:
            part = text[start:pos].strip()
            if part:
                parts.append(part)
            start = pos
        last = text[start:].strip()
        if last:
            parts.append(last)
        if len(parts) > 1:
            return parts'''

count = content.count(old_positions)
print(f"\nOld positions pattern found {count} time(s)")
if count == 1:
    content = content.replace(old_positions, new_positions)
    print("Positions fix applied.")
else:
    # Try to find it with different quoting
    idx = content.find('    positions = [\n        match.start()')
    print(f"  Fallback search found at: {idx}")
    if idx != -1:
        print(repr(content[idx:idx+300]))

# --- Step 3: Fix the label.lower() check in _format_item (active version) ---
old_quote_check = '        if label.lower() in {"quote", "quotes", "pipeline"} and not rest.startswith(">"):\n            rest = f"> {rest}"'
new_quote_check = '        if _re.search(r"\\bquotes?\\b|\\bpipeline\\b", label.lower()) and not rest.startswith(">"):\n            rest = f"> {rest}"'

count3 = content.count(old_quote_check)
print(f"\nQuote check pattern found {count3} time(s)")
if count3 == 1:
    content = content.replace(old_quote_check, new_quote_check)
    print("Quote check fix applied.")

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nDone! app.py updated.")
