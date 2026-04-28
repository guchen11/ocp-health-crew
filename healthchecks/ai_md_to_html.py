"""Markdown to HTML for AI RCA report sections."""


def _md_to_html(md_text):
    """Convert markdown to HTML with dark-theme styling.

    Handles fenced code blocks, headers, bold, inline code, bullet/numbered
    lists, and horizontal rules. Operates line-by-line with a state machine
    for code fences.
    """
    import re
    from html import escape

    lines = md_text.split("\n")
    out = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Fenced code block toggle (handles indented fences too)
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                out.append(
                    '<pre style="background:#1a1a2e;border:1px solid #333;'
                    "border-radius:6px;padding:12px 16px;margin:10px 0;"
                    "overflow-x:auto;font-size:0.88em;color:#d4d4d4;"
                    'line-height:1.5">'
                )
                continue
            else:
                in_code_block = False
                out.append("</pre>")
                continue

        if in_code_block:
            out.append(escape(line))
            out.append("\n")
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", stripped):
            out.append('<hr style="border:none;border-top:1px solid #333;margin:16px 0">')
            continue

        # Empty line
        if not stripped:
            out.append("<br>")
            continue

        # Escape HTML entities in the line
        safe = escape(stripped)

        # Headers (process before inline formatting)
        m = re.match(r"^(#{1,5})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = escape(m.group(2))
            title = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", title)
            title = re.sub(
                r"`([^`]+)`",
                r'<code style="background:#2a2a3d;padding:2px 6px;'
                r'border-radius:3px;color:#FF9830">\1</code>',
                title,
            )
            colors = {1: "#5794F2", 2: "#5794F2", 3: "#73BF69", 4: "#FF9830", 5: "#FF9830"}
            sizes = {1: "1.4em", 2: "1.25em", 3: "1.1em", 4: "1.0em", 5: "0.95em"}
            tag = f"h{min(level + 1, 6)}"
            out.append(
                f'<{tag} style="color:{colors.get(level, "#ccc")};'
                f"font-size:{sizes.get(level, '1em')};"
                f'margin:20px 0 8px 0">{title}</{tag}>'
            )
            continue

        # Inline formatting: bold, inline code
        safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
        safe = re.sub(
            r"`([^`]+)`",
            r'<code style="background:#2a2a3d;padding:2px 6px;'
            r'border-radius:3px;color:#FF9830">\1</code>',
            safe,
        )

        # Bullet lists (* or -)
        m = re.match(r"^[\*\-]\s+(.+)$", stripped)
        if m:
            content = escape(m.group(1))
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(
                r"`([^`]+)`",
                r'<code style="background:#2a2a3d;padding:2px 6px;'
                r'border-radius:3px;color:#FF9830">\1</code>',
                content,
            )
            out.append(
                f'<div style="padding:3px 0 3px 20px">'
                f'<span style="color:#5794F2;margin-right:8px">&#x2022;</span>{content}</div>'
            )
            continue

        # Numbered lists
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            num = m.group(1)
            content = escape(m.group(2))
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(
                r"`([^`]+)`",
                r'<code style="background:#2a2a3d;padding:2px 6px;'
                r'border-radius:3px;color:#FF9830">\1</code>',
                content,
            )
            out.append(
                f'<div style="padding:3px 0 3px 20px">'
                f'<span style="color:#73BF69;margin-right:8px;font-weight:bold">{num}.</span>{content}</div>'
            )
            continue

        # Indented sub-items (4+ spaces then * or - or digit)
        m = re.match(r"^\s{2,}[\*\-]\s+(.+)$", line)
        if m:
            content = escape(m.group(1))
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(
                r"`([^`]+)`",
                r'<code style="background:#2a2a3d;padding:2px 6px;'
                r'border-radius:3px;color:#FF9830">\1</code>',
                content,
            )
            out.append(
                f'<div style="padding:2px 0 2px 40px">'
                f'<span style="color:#888;margin-right:6px">&#x25E6;</span>{content}</div>'
            )
            continue

        m = re.match(r"^\s{2,}(\d+)\.\s+(.+)$", line)
        if m:
            num = m.group(1)
            content = escape(m.group(2))
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(
                r"`([^`]+)`",
                r'<code style="background:#2a2a3d;padding:2px 6px;'
                r'border-radius:3px;color:#FF9830">\1</code>',
                content,
            )
            out.append(
                f'<div style="padding:2px 0 2px 40px">'
                f'<span style="color:#888;margin-right:6px">{num}.</span>{content}</div>'
            )
            continue

        # Regular paragraph line
        out.append(f"<div>{safe}</div>")

    # Close unclosed code block
    if in_code_block:
        out.append("</pre>")

    return "\n".join(out)
