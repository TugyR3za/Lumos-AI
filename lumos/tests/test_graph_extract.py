"""Graph V1 slice 1: extraction is deterministic and honest.

Only what a note literally contains becomes a reference; code, URLs, and
malformed syntax never mint links or tags.
"""

from lumos.graph.extract import NoteRefs, extract_refs, normalize_tag, slugify


def test_slugify_normalizes_titles():
    assert slugify("Kitchen Renovation") == "kitchen-renovation"
    assert slugify("  Budget  2026! ") == "budget-2026"
    assert slugify("snake_case and-dashes") == "snake-case-and-dashes"
    assert slugify("v0.1 Notes") == "v01-notes"
    assert slugify("Café") == "café"  # unicode word characters survive
    assert slugify("Groß") == "gross"  # casefold, not lower
    assert slugify("!!!") == ""


def test_normalize_tag_segments_and_numbers():
    assert normalize_tag("#Home/Kitchen Reno") == "home/kitchen-reno"
    assert normalize_tag("ProjectX") == "projectx"
    assert normalize_tag("#2026") == ""  # pure number is not a tag
    assert normalize_tag("2026-07") == "2026-07"
    assert normalize_tag("///") == ""


def test_wikilink_basic_alias_and_heading_anchor():
    refs = extract_refs(
        "See [[Kitchen Renovation]], [[Budget 2026|the budget]], and [[Plan#Phase 2]]."
    )
    assert [link.slug for link in refs.links] == ["kitchen-renovation", "budget-2026", "plan"]
    assert refs.links[0].display is None
    assert refs.links[1].target == "Budget 2026"
    assert refs.links[1].display == "the budget"
    assert refs.links[2].target == "Plan"  # '#Phase 2' anchor dropped


def test_wikilink_dedupes_by_slug_keeping_first_form():
    refs = extract_refs("[[Kitchen Reno]] then [[kitchen reno]] again")
    assert len(refs.links) == 1
    assert refs.links[0].target == "Kitchen Reno"


def test_wikilink_invalid_forms_are_ignored():
    refs = extract_refs("[[]] [[   ]] [[|display only]] [[#Heading only]] [[!!!]]")
    assert refs.links == ()


def test_embed_syntax_counts_as_a_link():
    refs = extract_refs("![[floorplan.png]]")
    assert [link.slug for link in refs.links] == ["floorplanpng"]


def test_tags_basic_nested_and_lowercased():
    refs = extract_refs("Work on #Home/Kitchen and #ProjectX today")
    assert refs.tags == ("home/kitchen", "projectx")


def test_tags_exclude_headings_midword_and_pure_numbers():
    text = "# Heading\n## Sub\nprice#tag nope\n#2026\n#2026-07 ok\nemail@x.com #real"
    refs = extract_refs(text)
    assert refs.tags == ("2026-07", "real")


def test_code_is_invisible_to_extraction():
    text = (
        "Real #tag and [[Real Link]]\n"
        "```python\n"
        "# not a tag, just a comment\n"
        "x = data[[0]]  # [[not a link]]\n"
        "```\n"
        "`#inline` and `[[inline link]]` are hidden too\n"
        "~~~\n"
        "#also-hidden\n"
        "~~~\n"
    )
    refs = extract_refs(text)
    assert [link.slug for link in refs.links] == ["real-link"]
    assert refs.tags == ("tag",)


def test_unclosed_fence_drops_the_rest_of_the_note():
    refs = extract_refs("#kept\n```\n#dropped\n[[Dropped]]\n")
    assert refs.tags == ("kept",)
    assert refs.links == ()


def test_urls_do_not_leak_tags():
    text = "see https://github.com/x/y#readme and #legit\n[docs](https://ex.com#frag)"
    refs = extract_refs(text)
    assert refs.tags == ("legit",)


def test_frontmatter_inline_and_block_lists():
    text = (
        "---\n"
        "title: Kitchen\n"
        "tags: [Home, reno/kitchen]\n"
        "aliases:\n"
        "  - Kitchen Reno\n"
        '  - "The Big Project"\n'
        "---\n"
        "Body #extra\n"
    )
    refs = extract_refs(text)
    assert refs.tags == ("home", "reno/kitchen", "extra")
    assert refs.aliases == ("Kitchen Reno", "The Big Project")


def test_frontmatter_comma_scalar_and_hash_prefix():
    refs = extract_refs("---\ntags: #home, garden\n---\n")
    assert refs.tags == ("home", "garden")


def test_frontmatter_only_whitelisted_keys_and_only_at_top():
    # a 'tags:' line in the body is plain text, not frontmatter
    refs = extract_refs("no frontmatter here\ntags: [x, y]\n")
    assert refs.tags == ()
    # unterminated block: everything is body; the trailing tag still counts
    refs = extract_refs("---\ntags: [x]\nno closing fence\n#body-tag")
    assert refs.tags == ("body-tag",)
    assert refs.aliases == ()


def test_frontmatter_tags_dedupe_against_body_tags():
    refs = extract_refs("---\ntags: [home]\n---\n#home #home #garden")
    assert refs.tags == ("home", "garden")


def test_empty_note_and_crlf_input():
    assert extract_refs("") == NoteRefs()
    refs = extract_refs("---\r\ntags: [a]\r\n---\r\n[[X]] #b\r\n")
    assert refs.tags == ("a", "b")
    assert [link.slug for link in refs.links] == ["x"]
