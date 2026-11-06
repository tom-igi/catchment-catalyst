"""Hand-written text (typed into Excel) as part of a web page.

Every text box on the dashboard (River Status Text, Location Text, the "i"
buttons in Datasets) uses the same few marks, taken from Markdown, so they can
be typed into an Excel cell (Alt+Enter starts a new line in a cell):

    A blank line                  starts a new paragraph. A single new line is kept as one.
    - or • at the start of a line a bullet point. Two spaces before it puts it inside the
                                  bullet above.
    **words**                     bold
    [words](https://...)          a link. Web and email addresses become links by themselves.
    ## Heading                    a heading
    ### Section                   a section that opens and closes when its name is clicked,
                                  up to the next ## or ###. The first one starts open.
    #### Heading                  a smaller heading, e.g. inside a section
    > words                       a paragraph in a grey box

Anything else, such as HTML, is shown just as it was typed.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markupsafe import Markup

# Only the marks above: nothing else in Markdown (e.g. pictures, code, or a line of dashes
# becoming a rule) changes what was typed.
_markdown = MarkdownIt("zero", {"breaks": True, "linkify": True, "html": False}).enable([
    "heading", "list", "blockquote", "emphasis", "link", "linkify", "newline", "entity",
])

# A bullet as typed in Excel or pasted from Word: •, -, – or * (the last three with a space after).
BULLET = re.compile(r"^([ \t]*)(?:•[ \t]*|[-–*][ \t]+)(?=\S)")
SECTION_START = '<details class="section"{open}>\n<summary>{title}</summary>\n<div class="section-body">\n'
SECTION_END = "</div>\n</details>\n"


def formatted(text: str | None) -> Markup:
    """The text as HTML: paragraphs, bullets, bold, links, headings and sections."""
    if not text or not text.strip():
        return Markup("")
    env: dict = {}
    tokens = _markdown.parse(_prepare(text), env)

    def render(part: list[Token]) -> str:
        return _markdown.renderer.render(part, _markdown.options, env)

    html, part, in_section, first = [], [], False, True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # A heading at the top level (not inside a bullet) ends the section before it, and a
        # ### heading starts a new one.
        if token.type == "heading_open" and token.level == 0 and token.tag in ("h2", "h3"):
            html.append(render(part))
            part = []
            if in_section:
                html.append(SECTION_END)
                in_section = False
            if token.tag == "h3":
                title = _markdown.renderer.renderInline(tokens[i + 1].children or [], _markdown.options, env)
                html.append(SECTION_START.format(open=" open" if first else "", title=title))
                in_section, first = True, False
                i += 3  # the heading's start, its words and its end
                continue
        part.append(token)
        i += 1
    html.append(render(part))
    if in_section:
        html.append(SECTION_END)
    return Markup("".join(html).strip())  # the parts are made by markdown-it, which escapes what was typed


def _prepare(text: str) -> str:
    """Bullets as Markdown expects them ("- "), however they were typed."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.replace("\t", "    ")
        bullet = BULLET.match(line)
        if bullet:
            words = line[bullet.end():]
            if words.startswith(">"):  # e.g. "• > 0.03 = Very High" is a bullet, not a grey box
                words = "&gt;" + words[1:]
            line = bullet.group(1) + "- " + words
        lines.append(line)
    return "\n".join(lines)
