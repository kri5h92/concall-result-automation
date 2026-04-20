"""Test the formatting improvements against real JSON data."""
import json
import sys
sys.path.insert(0, '.')

# Import the formatting functions from app.py
# We need to import them carefully since they depend on streamlit
import importlib, types

# Manually import only the formatting functions
import re as _re

def _clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _is_not_disclosed(value) -> bool:
    NOT_DISCLOSED_VALUES = {"", "n/a", "na", "none", "not available", "not disclosed"}
    text = _clean_text(value).lower().strip(" .:-_")
    return text in NOT_DISCLOSED_VALUES

def _format_quote_blocks(text: str) -> str:
    text = _clean_text(text)
    def replace_double(match):
        label = match.group(1).title()
        quote = match.group(2).strip()
        return f"\n\n**{label}**\n> {quote}\n"
    def replace_single(match):
        label = match.group(1).title()
        quote = match.group(2).strip()
        return f"\n\n**{label}**\n> {quote}\n"
    text = _re.sub(r"\(\s*(Quote|Quotes|Pipeline)\s*:\s*", r"\n\n\1: ", text, flags=_re.IGNORECASE)
    text = _re.sub(r'(?i)\b(Quote|Quotes|Pipeline)\b\s*:\s*"([^"]{5,}?)"', replace_double, text)
    text = _re.sub(r"(?i)\b(Quote|Quotes|Pipeline)\b\s*:\s*'([^']{5,}?)'", replace_single, text)
    text = _re.sub(r'(?i)\b(Quote|Quotes|Pipeline)\b\s+"([^"]{5,}?)"', replace_double, text)
    text = _re.sub(r"(?i)\b(Quote|Quotes|Pipeline)\b\s+'([^']{5,}?)'", replace_single, text)
    if text.startswith('"') and text.endswith('"') and len(text) > 10:
        return f"> {text[1:-1]}"
    if text.startswith("'") and text.endswith("'") and len(text) > 10:
        return f"> {text[1:-1]}"
    return text.strip()

def _format_item(text: str) -> str:
    text = _clean_text(text)
    if _is_not_disclosed(text):
        return "_Not disclosed_"
    prefix = ""
    bullet_match = _re.match(r"^((?:[-*\u2022])\s+|\d{1,2}[\.\)]\s+)", text)
    if bullet_match:
        prefix = bullet_match.group(1)
        text = text[bullet_match.end():].strip()
    if text.endswith(":") and not _re.search(r"[.!?]", text[:-1]):
        return f"**{prefix}{text[:-1].strip()}**" if prefix else f"**{text[:-1].strip()}**"
    colon = text.find(": ")
    if 0 < colon < 80 and not _re.search(r"[.!?]", text[:colon]):
        label = text[:colon].strip()
        rest = _format_quote_blocks(text[colon + 2:].strip()) or "_Not disclosed_"
        if _re.search(r"\bquotes?\b|\bpipeline\b", label.lower()) and not rest.startswith(">"):
            rest = f"> {rest}"
        return f"**{prefix}{label}**\n{rest}"
    formatted = _format_quote_blocks(text)
    if prefix and formatted.startswith(">"):
        return f"**{prefix.strip()}**\n{formatted}"
    return f"{prefix}{formatted}" if prefix else formatted

def _parse_items_safe(text: str) -> list:
    text = _clean_text(text)
    if not text:
        return []
    blocks = [block.strip() for block in _re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) > 1:
        def is_short_block(block):
            words = block.split()
            return len(words) <= 3 and len(block) <= 24 and not _re.search(r"[.:;!?]", block)
        merged_blocks = []
        pending = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            lower = block.lower()
            if lower in {"quote", "quotes", "pipeline"} and i + 1 < len(blocks):
                if pending:
                    merged_blocks.append(" ".join(pending).strip())
                    pending = []
                merged_blocks.append(f"{block}: {blocks[i + 1]}")
                i += 2
                continue
            if is_short_block(block):
                pending.append(block)
                i += 1
                continue
            if pending:
                merged_blocks.append(" ".join(pending + [block]).strip())
                pending = []
            else:
                merged_blocks.append(block)
            i += 1
        if pending:
            merged_blocks.append(" ".join(pending).strip())
        if len(merged_blocks) > 1:
            return merged_blocks

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        items = []
        current = []
        for line in lines:
            starts_new = bool(
                _re.match(r"^((?:[-*\u2022])|\d{1,2}[\.\)])\s+", line)
                or _re.match(r"^[A-Z][^:]{1,70}:\s", line)
            )
            if current and starts_new:
                items.append(" ".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            items.append(" ".join(current).strip())
        if len(items) > 1:
            return items

    if " | " in text:
        parts = [part.strip() for part in text.split(" | ") if part.strip()]
        if len(parts) > 1:
            return parts

    candidate_numbered = [part.strip() for part in _re.split(r"(?<!\w)(?=\d{1,2}[\.\)]\s)", text) if part.strip()]
    has_leading_text = False
    numbered_values = []
    normalized_parts = []
    for idx, part in enumerate(candidate_numbered):
        match = _re.match(r"^(\d{1,2})[\.\)]\s+", part)
        if not match:
            if idx == 0:
                has_leading_text = True
                normalized_parts.append(part)
            elif normalized_parts:
                normalized_parts[-1] = f"{normalized_parts[-1]} {part}".strip()
            else:
                normalized_parts.append(part)
            continue
        number = int(match.group(1))
        if not numbered_values or number == numbered_values[-1] + 1:
            normalized_parts.append(part)
            numbered_values.append(number)
        elif normalized_parts:
            normalized_parts[-1] = f"{normalized_parts[-1]} {part}".strip()
        else:
            normalized_parts.append(part)
    if (
        len(numbered_values) >= 2
        and (numbered_values[0] == 1 or (has_leading_text and numbered_values[0] == 2))
        and all(curr == prev + 1 for prev, curr in zip(numbered_values, numbered_values[1:]))
    ):
        if has_leading_text and numbered_values[0] == 2:
            return [f"1. {normalized_parts[0]}"] + normalized_parts[1:]
        return normalized_parts

    # Fixed: require sentence boundary before label split
    positions = [
        m.end(1)
        for m in _re.finditer(
            r"([.!?]['\"\u2019]?\s+)(?=[A-Z][A-Za-z0-9/&'()%-]{1,25}(?:\s[A-Za-z0-9/&'()%-]{1,25}){0,7}:\s)",
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
            return parts

    return [text]

def _format_as_markdown(value) -> str:
    items = _parse_items_safe(_clean_text(value))
    if not items:
        return "_Not available_"
    return "\n\n".join(_format_item(item) for item in items)


# --- Run tests ---
files = [
    ("ANANDRATHI", "Apr 2026", "analysis_anthropic-claude-4.6-opus.json"),
    ("ANGELONE", "Jan 2026", "analysis_anthropic-claude-4.6-opus.json"),
    ("BOSCHLTD", "Apr 2026", "analysis_anthropic-claude-4.6-opus.json"),
]

for ticker, period, fname in files:
    path = f"Outputs/Concalls/{ticker}/{period}/{fname}"
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\n{'='*60}")
    print(f"{ticker} / {period}")
    print('='*60)
    
    for section in ["financial_guidance", "growth_drivers", "quarter_change", "margins_commentary"]:
        print(f"\n--- {section} ---")
        rendered = _format_as_markdown(data.get(section, ""))
        # Print first 600 chars
        print(rendered[:600])
        if len(rendered) > 600:
            print(f"  ... ({len(rendered)} total chars)")
