"""Deterministic reference extraction from note text (Graph V1, slice 1).

Pulls the raw material for graph edges out of a markdown note: outgoing
``[[wikilinks]]``, ``#tags``, and the whitelisted ``tags:`` / ``aliases:``
frontmatter keys. Pure text-in, values-out — no database, no LLM, no new
dependencies. The notes ingestor wires these results into graph tables in a
later slice.

Extraction is deliberately conservative: fenced code blocks, inline code
spans, and URLs are invisible to it, and anything that fails to parse is
simply not a reference. Under-extraction is always preferred over garbage
edges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
# A tag needs a non-word, non-'#' character before it ('#x' at line start is
# fine, 'price#x' and '##heading' are not) and at least one non-digit overall,
# mirroring Obsidian: '#2026' is a number, '#2026-07' is a tag.
_TAG_RE = re.compile(r"(?<![\w#])#([\w/-]+)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_URL_RE = re.compile(r"https?://\S+")
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
_FM_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
_FM_ITEM_RE = re.compile(r"^\s*-\s+(.*)$")
_SLUG_JUNK_RE = re.compile(r"[^\w-]+")
_HYPHEN_RUN_RE = re.compile(r"-{2,}")

_FRONTMATTER_KEYS = ("tags", "aliases")


@dataclass(frozen=True, slots=True)
class WikiLink:
    """One outgoing ``[[...]]`` reference, with any ``#anchor`` removed."""

    target: str
    slug: str
    display: str | None = None


@dataclass(frozen=True, slots=True)
class NoteRefs:
    """Everything one note declares about the graph, in document order."""

    links: tuple[WikiLink, ...] = ()
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


def slugify(text: str) -> str:
    """Normalize a human-written name into a stable node key.

    'Kitchen Renovation!' -> 'kitchen-renovation'. Unicode word characters
    survive so non-English titles keep distinct slugs.
    """
    hyphenated = re.sub(r"[\s_]+", "-", text.strip().casefold())
    return _HYPHEN_RUN_RE.sub("-", _SLUG_JUNK_RE.sub("", hyphenated)).strip("-")


def normalize_tag(raw: str) -> str:
    """'#Home/Kitchen Reno' -> 'home/kitchen-reno'; '' when nothing tag-like remains."""
    segments = (slugify(part) for part in raw.lstrip("#").split("/"))
    tag = "/".join(part for part in segments if part)
    if not tag or tag.isdigit():
        return ""
    return tag


def extract_refs(text: str) -> NoteRefs:
    """Extract wikilinks, tags, and aliases from one note's raw text."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter, body = _split_frontmatter(normalized)
    body = _strip_code_and_urls(body)

    links: list[WikiLink] = []
    seen_links: set[str] = set()
    for match in _WIKILINK_RE.finditer(body):
        link = _parse_wikilink(match.group(1))
        if link is not None and link.slug not in seen_links:
            seen_links.add(link.slug)
            links.append(link)

    tags: list[str] = []
    seen_tags: set[str] = set()
    candidates = [*frontmatter.get("tags", []), *(m.group(1) for m in _TAG_RE.finditer(body))]
    for raw in candidates:
        tag = normalize_tag(raw)
        if tag and tag not in seen_tags:
            seen_tags.add(tag)
            tags.append(tag)

    aliases: list[str] = []
    seen_aliases: set[str] = set()
    for raw in frontmatter.get("aliases", []):
        alias = raw.strip()
        slug = slugify(alias)
        if slug and slug not in seen_aliases:
            seen_aliases.add(slug)
            aliases.append(alias)

    return NoteRefs(links=tuple(links), tags=tuple(tags), aliases=tuple(aliases))


def _parse_wikilink(inner: str) -> WikiLink | None:
    target_part, _, display_part = inner.partition("|")
    target = target_part.partition("#")[0].strip()
    slug = slugify(target)
    if not target or not slug:
        return None
    display = display_part.strip() or None
    return WikiLink(target=target, slug=slug, display=display)


def _strip_code_and_urls(text: str) -> str:
    """Drop fenced code blocks, then inline code spans and URLs, line by line."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        marker = _FENCE_RE.match(line)
        if fence is None:
            if marker:
                fence = marker.group(1)
                continue
            kept.append(_URL_RE.sub("", _INLINE_CODE_RE.sub("", line)))
        elif marker and marker.group(1) == fence:
            fence = None
        # Lines inside a fence are dropped; an unclosed fence drops to the end,
        # which under-extracts rather than minting tags from code comments.
    return "\n".join(kept)


def _split_frontmatter(text: str) -> tuple[dict[str, list[str]], str]:
    """Split a leading '---' block off the note and read whitelisted keys.

    Hand-rolled on purpose: no YAML dependency, and the graph only needs the
    'tags' and 'aliases' lists. An unterminated or absent block means the
    whole text is body.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")),
        None,
    )
    if end is None:
        return {}, text

    data: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        item = _FM_ITEM_RE.match(line)
        if item is not None:
            if current is not None:
                value = _unquote(item.group(1))
                if value:
                    data[current].append(value)
            continue
        key_match = _FM_KEY_RE.match(line)
        if key_match is None:
            current = None
            continue
        key = key_match.group(1).casefold()
        if key not in _FRONTMATTER_KEYS:
            current = None
            continue
        values = data.setdefault(key, [])
        rest = key_match.group(2).strip()
        if rest:
            values.extend(_split_inline_list(rest))
            current = None
        else:
            current = key
    return data, "\n".join(lines[end + 1 :])


def _split_inline_list(rest: str) -> list[str]:
    """'[a, b]' or 'a, b' -> ['a', 'b']; per-item quoting is honored."""
    if rest.startswith("[") and "]" in rest:
        rest = rest[1 : rest.index("]")]
    values = [_unquote(part) for part in rest.split(",")]
    return [value for value in values if value]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value
