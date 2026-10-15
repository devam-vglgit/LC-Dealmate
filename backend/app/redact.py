"""Decide what a contract is allowed to tell the model.

This is the outbound boundary for CMS data, and it is an allowlist in the same
sense as `terms.py`: a fixed set of named fields is copied out, and everything
else — clause prose, signatories, addresses, bank details, internal owners — is
absent by construction rather than removed by a pattern that has to anticipate
it. Anything this module does not know about cannot leave.

Two things do get pattern-stripped, because they are woven into fields we want
to keep rather than living in fields of their own:

  * our own identity. The counterparty is worth naming — you cannot research
    Nexstar's rate card without saying "Nexstar" — but who *we* are adds nothing
    to a benchmark. Every contract in the portfolio names us, under at least
    eight spellings, usually inside the same string as the vendor.
  * internal reference codes (``SLCI-VA-002705``), which prefix most titles and
    are both identifying and useless to the model.

Individual counterparties are replaced rather than named. Roughly a fifth of the
portfolio is contracted to a private person — a host, a model, a presenter — and
sending "Cheryl Ells, $X per appearance" to a third party is both a privacy
problem and pointless, since no public benchmark exists for an individual.

The classifier is tuned against the real vendor list, which is messier than the
obvious rules assume: `Comcast Cable`, `Rakuten Marketing`, `KOBI TV` and
`Numerous.ai` are all two-token companies with no corporate suffix, and real
people arrive as `Daniel J. Dennis. Jr.` and `Abby W Cross`. So company markers
are tested first and a personal-name shape is only accepted once none matched.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# ---------------------------------------------------------------- our identity

# Every legal entity, trading name and former name the company appears under.
# `parties` mixes these with the counterparty in one string, so they are removed
# from the text rather than filtered out as whole values.
_OUR_ENTITY = re.compile(
    r"""(?ix)
    \b(?:the\s+)?
    (?:
        shop\s*lc
      | slc[il]\b
      | jewelry\s+channel
      | liquidation\s+channel
      | vaibhav\s+global
      | vgl\s+group
      | infomercial\s+sales
    )
    (?:\s+global)?                      # "Shop LC Global"
    (?:\s*,?\s*(?:inc|llc|ltd)\b\.?)?   # "…, Inc." / "… LLC"
    (?:\s*\((?:customer|buyer)\))?      # "… (Customer)"
    """
)

# Contract prose abbreviates us to a bare "LC" — "Station will invoice LC in
# advance", "launch of LC on the Orlando station". Caught separately from the
# full names above because it has to run after them, and because it needs a
# strict word boundary: without one it eats the "LC" inside "LLC", which appears
# in most counterparty names in this portfolio.
_OUR_SHORT = re.compile(r"\bLC\b")

# "SLCI-VA-002705", "SLCI-VA-000892_KM", "SLCI-VA-002338\t- ". No trailing \b:
# an underscore is a word character, so "…000892_KM" offers no boundary after
# the digits and the whole code was left in place with only "SLCI" stripped.
_REF_CODE = re.compile(r"\bSLC[IL][-\s_]*VA[-\s_]*\d+", re.IGNORECASE)

# Some titles carry the two characters backslash-t rather than a tab. Left in,
# they pad a name to four tokens and defeat the personal-name shape — which is
# how "Abby W Cross" was classified as a company and her name kept.
_LITERAL_ESCAPE = re.compile(r"\\[tnr]")

# Left behind once the entity either side of it is gone.
_DANGLING_DBA = re.compile(r"(?i)\bd/?b/?a\b\.?")

# "X d/b/a Y" — only an organisation trades under another name, so this rescues
# companies whose own name carries no corporate token (DigitalEx d/b/a Mavvrik).
# A word is required on both sides: once our own entity is removed, a bare
# "d/b/a" can be left dangling next to a private individual, and treating that
# as a company signal would publish their name.
_TRADE_MARKER = re.compile(r"(?i)[A-Za-z0-9.]\s*\bd/?b/?a\b\.?\s*[A-Za-z0-9]")

_PLACEHOLDER_COMPANY = "our company"
PLACEHOLDER_PERSON = "[an individual contractor]"

# ------------------------------------------------------- company vs individual

# A token that only ever appears in an organisation's name. Checked before any
# personal-name shape, so a two-word company is not mistaken for a person.
_COMPANY_MARKERS = frozenset(
    """
    inc inc. llc l.l.c. ltd ltd. limited corp corp. corporation co co. company companies
    group holdings holding partners partnership lp llp plc gmbh bv sa ag pvt nv
    media broadcasting broadcast communications communication network networks
    productions production studios entertainment television tv radio cable telecom
    telecommunications wireless satellite marketing advertising agency associates
    enterprises ventures capital services service solutions systems technologies
    technology digital global international national worldwide industries
    intelligence analytics consulting consultants ministries church foundation
    university institute college school hospital bank financial insurance
    sales reach frontier post outlet channel channels station stations
    lab labs laboratory laboratories studio software firm logistics
    pte pty sarl
    """.split()
)

# Station call letters — KOBI, WXXA, KJLA, WBWP. Two to four letters after a
# leading K or W, which is how US broadcast licences are issued.
_CALL_SIGN = re.compile(r"^[KW][A-Z]{2,3}(?:-[A-Z]{2,3})?$")

# Generational suffixes are part of a person's name, not evidence of a company.
_PERSON_SUFFIX = frozenset({"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "md", "phd"})

# A web address or product-style name is an organisation however short it is.
_WEBBY = re.compile(r"(?i)\.(?:ai|com|io|net|org|co|tv)\b")


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name.strip()) if t]


def looks_like_company(name: str) -> bool:
    """True when anything in the name marks it as an organisation.

    Deliberately tested first and generously: a missed company marker only costs
    a lost benchmark, whereas a missed *person* marker leaks a private name.
    """
    if not name:
        return False
    if _WEBBY.search(name):
        return True
    # Digits, ampersands and brackets belong to org names, never to a person's.
    if re.search(r"[\d&()/]", name):
        return True
    for token in _tokens(name):
        bare = token.strip(".,").lower()
        if bare in _PERSON_SUFFIX:
            continue
        if bare in _COMPANY_MARKERS:
            return True
        if _CALL_SIGN.match(token.strip(".,")):
            return True
    return False


def looks_like_person(name: str) -> bool:
    """True for a plain personal name — two or three words, no org markers.

    Only reached when `looks_like_company` found nothing, so this decides the
    residue rather than competing with it. A middle initial ("Sherry W. Witt")
    and a generational suffix ("Daniel J. Dennis. Jr.") both stay personal.
    """
    if not name or looks_like_company(name):
        return False

    parts = [t.strip(".,") for t in _tokens(name)]
    parts = [p for p in parts if p and p.lower() not in _PERSON_SUFFIX]
    if not 2 <= len(parts) <= 3:
        return False
    for part in parts:
        if not part.isalpha():
            return False
        # An all-caps run is a call sign or an acronym, not a first name.
        if part.isupper() and len(part) > 1:
            return False
        if not part[0].isupper():
            return False
    return True


# ------------------------------------------------------------------ scrubbing


def _tidy(text: str) -> str:
    """Close the punctuation gaps left where a removed name used to sit."""
    # "X (d/b/a Y)" where both X and Y were us leaves "our company ( our company )".
    out = re.sub(
        rf"(?i)\(\s*{_PLACEHOLDER_COMPANY}\s*\)", " ", text
    )
    out = re.sub(r"\(\s*\)", " ", out)                # "( )" once the name inside went
    out = re.sub(r"\s*([,&/])\s*(?=[,&/])", "", out)   # ", ," / ", &" collapse to one
    out = re.sub(r"[^\S\n]+([,;:.])", r"\1", out)      # " :" left where a name was
    # Horizontal whitespace only. A plain \s{2,} also eats the newline next to a
    # removed name, which ran the excerpt's "Parties:" and "Type:" lines together
    # and cost the model the structure it reads the summary by.
    out = re.sub(r"[^\S\n]{2,}", " ", out)
    out = re.sub(r"[^\S\n]*\n[^\S\n]*", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # "_" is in the strip set because CMS joins its reference code to the vendor
    # with one ("SLCI-VA-002705_Four Seasons"), leaving it stranded in front.
    return out.strip(" \n_,;:&/-–—")


def _without_us(text: str, *, placeholder: bool) -> str:
    """Our identity and reference codes gone; "d/b/a" deliberately still here."""
    mask = f" {_PLACEHOLDER_COMPANY} " if placeholder else " "
    out = _LITERAL_ESCAPE.sub(" ", str(text))
    out = _REF_CODE.sub(" ", out)
    out = _OUR_ENTITY.sub(mask, out)
    # After the long forms, so "Shop LC" is already gone and this only catches
    # the standalone abbreviation left in the prose.
    return _OUR_SHORT.sub(mask, out)


def strip_identifiers(text: str | None, *, placeholder: bool = True) -> str:
    """Remove our own names and internal reference codes from free text.

    `placeholder=True` leaves "our company" behind so a sentence still reads;
    that suits an excerpt. `placeholder=False` deletes the mention outright,
    which suits a party list, where naming ourselves as one of the parties is
    noise the model has no use for.
    """
    if not text:
        return ""
    out = _without_us(str(text), placeholder=placeholder)
    # "d/b/a" whose subject we just deleted now points at nothing.
    out = _DANGLING_DBA.sub(" ", out)
    if placeholder:
        # A string that was only ever us collapses to one placeholder.
        out = re.sub(
            rf"(?:{_PLACEHOLDER_COMPANY}[\s,&/]*)+", f"{_PLACEHOLDER_COMPANY} ", out
        )
    return _tidy(out)


def resolve_counterparty(raw: str | None) -> tuple[str, bool]:
    """(cleaned name, is_individual). One decision, two callers.

    `counterparty_of` needs the verdict and `person_names` needs the name that
    produced it, so both go through here rather than re-deriving it and drifting
    apart — a name classified as a person in one place and a company in the
    other would be withheld from the field but left standing in the excerpt.
    """
    if not raw:
        return "", False
    # Tested after our own name is gone, so a "d/b/a" that belonged to us can't
    # vouch for the counterparty, but one that is genuinely theirs still does.
    trades_as = bool(_TRADE_MARKER.search(_without_us(str(raw), placeholder=False)))
    cleaned = strip_identifiers(raw, placeholder=False)
    if not cleaned:
        return "", False
    return cleaned, (not trades_as and looks_like_person(cleaned))


def counterparty_of(raw: str | None) -> str:
    """The other side of the deal, with us and our reference codes removed.

    Returns the placeholder for an individual, the cleaned name for a company,
    and "" when nothing recognisable is left.
    """
    cleaned, is_person = resolve_counterparty(raw)
    if not cleaned:
        return ""
    return PLACEHOLDER_PERSON if is_person else cleaned


def person_names(items: Iterable[dict[str, Any]]) -> set[str]:
    """Every counterparty across the portfolio that resolves to a person.

    Collected so the same names can be struck out of an excerpt by exact match.
    Redacting known strings is reliable in a way that spotting a name in prose
    is not, which is why the excerpt is only ever scrubbed against this set.
    """
    found: set[str] = set()
    for item in items:
        for field in (item.get("vendor"), item.get("parties"), item.get("product")):
            cleaned, is_person = resolve_counterparty(field)
            if is_person:
                found.add(cleaned)
    return found


def scrub_excerpt(text: str | None, people: set[str], max_chars: int = 1300) -> str:
    """Strip our identity and any known individual's name out of an excerpt."""
    out = strip_identifiers(text)
    for name in sorted(people, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(name)}\b", PLACEHOLDER_PERSON, out, flags=re.IGNORECASE)
    out = out.strip()
    if max_chars and len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out


# ------------------------------------------------------------ broadcast calls

# A US broadcast licence is three or four letters starting with K or W, with an
# optional service suffix (-TV, -LD, -CD…). Extracted from filenames and titles
# because it is the one public key that turns a carriage fee into a rate: it
# resolves via the FCC to a market and a coverage population, which is the
# denominator none of the money columns carry.
#
# Only the call sign is taken, never the filename it came from — those routinely
# read "… Contract Shop LC (1).pdf" and would hand back the identity that the
# rest of this module exists to remove.
_CALL_SIGN_TOKEN = re.compile(r"\b([KW][A-Z]{2,3})(?:-([A-Z]{2}))?\d{0,2}\b")

# Three- and four-letter English words beginning with K or W match the call-sign
# shape exactly, and all-caps filenames are common enough that they would
# otherwise be reported as stations.
_NOT_CALL_SIGNS = frozenset(
    """
    WITH WEST WHEN WHAT WILL WORK WERE WELL WEEK WIDE WIRE WHOM WHILE WERE
    WAS WHO WAY WIN WAR WON WET WHY WOW WALL WANT WARD WARM WAVE WEAR WISE
    WOOD WORD WORE WORN WRAP WRIT WAGE WAIT WAKE WALK WEND WHOA
    KEY KIT KID KEEP KEPT KIND KING KNEW KNOW
    """.split()
)


def call_signs(item: dict[str, Any]) -> list[str]:
    """Candidate broadcast call signs mentioned anywhere in a contract's labels.

    Heuristic, and flagged as such to the model: the shape is shared with
    ordinary words, so a stopword list carries most of the weight and a wrong
    guess is expected to fail its FCC lookup rather than mislead.
    """
    found: list[str] = []
    for field in ("document_name", "product", "vendor", "parties"):
        for base, suffix in _CALL_SIGN_TOKEN.findall(str(item.get(field) or "")):
            if base in _NOT_CALL_SIGNS:
                continue
            sign = f"{base}-{suffix}" if suffix else base
            if sign not in found:
                found.append(sign)
    return found


# --------------------------------------------------------------- model blocks
#
# Everything below builds the text actually placed in a model request. The
# allowlist is the tuple of fields read here: a column that is not named cannot
# reach the model, however the upstream row grows. Deliberately absent:
#   owner            — an internal employee, irrelevant to a benchmark
#   parties / title  — raw, un-scrubbed forms of the counterparty
#   description      — free prose, the thing the allowlist exists to exclude
#   document_name    — often the counterparty and a date, in a filename


def _money(value: Any, currency: str | None = "USD") -> str:
    if value in (None, ""):
        return "—"
    symbol = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹"}.get(currency or "USD", "")
    return f"{symbol}{float(value):,.0f}"


def _ref(item: dict[str, Any]) -> str:
    """A short handle so the model can cite a contract without naming anyone."""
    return str(item.get("id") or "")[:8] or "unknown"


def portfolio_block(items: list[dict[str, Any]], currency: str = "USD") -> str:
    """Every contract as one compact, de-identified row.

    A table rather than JSON: the same facts cost roughly a third of the tokens,
    which matters because this block is resent on every turn (cached, but still
    counted on a cache miss).
    """
    people = person_names(items)
    lines = [
        "ref | counterparty | station | type | dept | annual | recorded (basis) | "
        "ends | days | notice | status"
    ]
    stations = 0
    for item in sorted(items, key=lambda i: i.get("days_until_renewal") or 10**9):
        days = item.get("days_until_renewal")
        notice = item.get("notice_period_days")
        signs = call_signs(item)
        stations += bool(signs)
        lines.append(
            " | ".join(
                (
                    _ref(item),
                    counterparty_of(item.get("vendor")) or "unnamed",
                    ",".join(signs) or "—",
                    str(item.get("category") or "—"),
                    str(item.get("department") or "—"),
                    _money(item.get("annual_cost"), item.get("currency") or currency),
                    f"{_money(item.get('recorded_value'), item.get('currency') or currency)}"
                    f" ({item.get('value_basis') or '—'})",
                    str(item.get("renewal_date") or "—"),
                    "—" if days is None else str(days),
                    "—" if notice is None else f"{notice}d",
                    str(item.get("status") or "—"),
                )
            )
        )

    # A notice period that is identical across most of the book is a form
    # default that nobody filled in, not a term that was negotiated the same way
    # 90 times. Said plainly, because the model otherwise computes a confident
    # cancellation deadline from it — and the deadline is the whole point.
    notices = [i.get("notice_period_days") for i in items if i.get("notice_period_days")]
    caveat = ""
    if notices:
        modal = max(set(notices), key=notices.count)
        share = notices.count(modal) / len(notices)
        if share >= 0.6:
            caveat = (
                f"\n- **Treat `notice` as unverified.** {notices.count(modal)} of "
                f"{len(notices)} contracts record exactly {modal} days, which is a "
                f"system default rather than {modal} separately negotiated terms. "
                "Where an open contract's extracted summary states a notice period, "
                "that text wins over this column. Say which one you used."
            )

    withheld = len(people)
    return (
        "<contract_portfolio>\n"
        f"{len(items)} live contracts from the company's contract-management "
        "system. This is real signed data, not a sample.\n\n"
        "Read the columns carefully before drawing conclusions:\n"
        "- `annual` is derived. Only ANNUAL and MONTHLY bases convert cleanly; "
        "UNKNOWN is the recorded total divided by the term, VARIABLE is the raw "
        "recorded figure, and REVENUE_SHARE cannot be annualised at all and shows "
        "as an em dash. Say so rather than totalling them as if they were equal.\n"
        "- `days` is days until the end date; negative means already expired.\n"
        "- `notice` is the cancellation notice period, so the real deadline is "
        f"`days` minus `notice`.{caveat}\n"
        "- These are vendor contracts of every kind — broadcast carriage, "
        "services, leases, consulting, licences. Most are not SaaS seat deals.\n"
        f"- `station` is a broadcast call sign found in the contract's own labels "
        f"({stations} of {len(items)} rows have one), and it is the only public "
        "key to what a carriage fee actually buys: look it up to get the market, "
        "the coverage contour and the population inside it, then judge the fee "
        "per thousand people rather than in isolation. Extraction is heuristic — "
        "if a call sign does not resolve to a real licence, discard it and say so "
        "rather than reasoning from it.\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"Counterparties that are private individuals ({withheld} of them) show as "
        f"'{PLACEHOLDER_PERSON}'. Their names are withheld deliberately; do not ask "
        "for them and do not try to research them.\n"
        "The company's own name is withheld too and appears as 'our company'.\n"
        "</contract_portfolio>"
    )


def focus_block(
    item: dict[str, Any],
    excerpt: str | None,
    people: set[str],
    currency: str = "USD",
) -> str:
    """The one contract the user has open, in more detail than the table."""
    money_currency = item.get("currency") or currency
    rows = [
        ("Reference", _ref(item)),
        ("Counterparty", counterparty_of(item.get("vendor")) or "not named"),
        ("Broadcast call sign", ", ".join(call_signs(item))),
        ("Contract type", item.get("category")),
        ("Department", item.get("department")),
        ("Status", item.get("status")),
        ("Recorded value", f"{_money(item.get('recorded_value'), money_currency)} "
                           f"({item.get('value_basis') or 'basis unknown'})"),
        ("Annualised", _money(item.get("annual_cost"), money_currency)),
        ("Pricing structure", item.get("pricing_structure")),
        ("Contract structure", item.get("contract_structure")),
        ("Start date", item.get("contract_start")),
        ("End date", item.get("renewal_date")),
        ("Days until end", item.get("days_until_renewal")),
        ("Renewal period", f"{item['renewal_period_months']} months"
                           if item.get("renewal_period_months") else None),
        ("Renewal terms", item.get("renewal_terms")),
        ("Notice period", f"{item['notice_period_days']} days"
                          if item.get("notice_period_days") is not None else None),
        ("Cancellation deadline in",
         f"{item['days_until_cancellation_deadline']} days"
         if item.get("days_until_cancellation_deadline") is not None else None),
    ]
    body = "\n".join(f"{label}: {value}" for label, value in rows if value not in (None, ""))

    scrubbed = scrub_excerpt(excerpt, people) if excerpt else ""
    summary = (
        "\n\nSummary extracted from the contract document by the contract system:\n"
        f"{scrubbed}"
        if scrubbed
        else "\n\nNo extracted summary is available for this contract."
    )

    return (
        "<open_contract>\n"
        "The contract the user currently has open. When they say \"this contract\", "
        "\"this vendor\" or \"they\", this is what they mean.\n\n"
        f"{body}{summary}\n"
        "</open_contract>"
    )
