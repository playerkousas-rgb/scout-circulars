#!/usr/bin/env python3
"""Deterministic daily Story-template allocation (stdlib only).

The daily queue only admits training/activity/service/competition notices.  Each
category has its own primary visual base(s).  If a category would reuse one of
its primary bases in the same daily batch, the three general-purpose "notice"
bases are consumed as shared overflow first.  This lets all nine AI bases help
avoid repetition without turning an ordinary notice into an ``other`` queue
item.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

AUTO_TEMPLATE_NAMES: dict[str, tuple[str, ...]] = {
    "training": ("train_blue", "train_orange", "train_green"),
    "competition": ("competition_gold_black",),
    "activity": ("activity_army",),
    "service": ("service_wanted",),
}

# These three bases were originally exposed only through the manual 「通告」
# designs. They are neutral enough to be used as overflow artwork, but never
# change the notice's actual category / CTA / queue eligibility.
NOTICE_OVERFLOW_TEMPLATE_NAMES: tuple[str, ...] = (
    "unc_scope",
    "unc_topsecret",
    "unc_glitch",
)


def pick_daily_template_names(items: Iterable[Mapping[str, object]]) -> list[str | None]:
    """Return one deterministic template name for every item in its given order.

    For each automatic category, its own base(s) are used before any repetition.
    Once that category needs another visual, consume the next still-unused notice
    overflow base *across the whole day*. Therefore different categories cannot
    accidentally take the same overflow base in one batch. Once all available
    overflow bases have been consumed, repetition resumes predictably.

    A non-automatic category returns ``None`` so a manual/legacy renderer can
    retain its own selection behaviour. The automatic queue does not emit those
    categories.
    """
    category_counts = {category: 0 for category in AUTO_TEMPLATE_NAMES}
    unused_overflow = list(NOTICE_OVERFLOW_TEMPLATE_NAMES)
    result: list[str | None] = []

    for item in items:
        category = str(item.get("category") or "")
        primary = AUTO_TEMPLATE_NAMES.get(category)
        if primary is None:
            result.append(None)
            continue

        seen = category_counts[category]
        category_counts[category] = seen + 1
        if seen < len(primary):
            result.append(primary[seen])
        elif unused_overflow:
            # Shared, not per-category: no two overflow assignments in this
            # day's batch receive the same AI base until all three are used.
            result.append(unused_overflow.pop(0))
        else:
            # All native bases for this category and all three generic bases
            # have been consumed. Re-use in a stable cycle from here onwards.
            reusable = primary + NOTICE_OVERFLOW_TEMPLATE_NAMES
            # Continue the same primary→overflow sequence from its beginning,
            # rather than immediately repeating the last overflow artwork.
            result.append(reusable[seen % len(reusable)])

    return result
