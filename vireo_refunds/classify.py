"""Rule-based reason classifier for refund tickets.

Reads the customer's message and the agent's closing note and returns the most likely
*true* refund reason, independent of the dropdown code the agent picked (GW-OTHER is
the first option in the dropdown and is heavily over-used).

Output labels are the policy codes, except FAULT-DOA-WTY: a product fault / wrong item
where the text does not tell us whether DOA-REPL or WTY-BUYBACK is right (that needs
the delivery date, which we do not have). Anything without a match is UNCLASSIFIED.
"""
import re

# Order matters: the first rule that matches wins. Payment problems and cancellations
# are checked before delivery/return words because their wording is the most specific.
RULES = [
    ("DUP-PAYMENT", r"charged twice|double (charge|payment|debit)|two entries|deducted twice|"
                    r"duplicate|amount deducted|payment (was )?(debited|deducted)|"
                    r"payment went through|paid but|after pay(ment)?|no order id|went to you but your site|"
                    r"debited,? no ord|page failed after"),
    ("CANCEL", r"cancel|change of mind|chnage of mind|wrong colou?r|ordered (this )?(by mistake|without asking)|"
               r"stop the shipment|don'?t ship|without asking"),
    ("PRICE-ADJ", r"discount|coupon|promo|festive offer|offer vanished|% off|price (drop|adj)|cart says|"
                  r"not applied"),
    ("LOST-TRANSIT", r"not (been )?(delivered|rcvd|received)|haven'?t received|never (came|arrived)|"
                     r"stuck on shipped|deliver?y delayed|dlvry delayed|dlvry|lost in transit|shipment not|ord not delivered|"
                     r"re-?shipped"),
    ("FAULT-DOA-WTY", r"damag|dent|crack|dead on arrival|\bdoa\b|won'?t (switch|turn|power)|not charging|"
                      r"wont charge|case dead|battery|crackl|distort|pairing|unable to pair|disconnect|"
                      r"mic(rophone)? |touch|silent|strap|different thing|incorrect product|wrong (item|product)|rma|"
                      r"warranty|buy-?back|sound|firmware|fw update|stutter|bluetooth|new unit|fresh unit"),
    ("RETURN-QC-OK", r"return|pickup|pkp|pick-up|refund (pending|delay|not|status)|rfnd (pending|delay|not)|"
                     r"money|amount is nowhere|reverse|qc|refund was promised|credited|nothing"),
]
_COMPILED = [(label, re.compile(rx, re.I)) for label, rx in RULES]

# Agent notes that say a replacement unit went out *in addition to* a refund.
# Checked fragment by fragment (split on | . newline --) so that a negation such as
# "rplc request rejected" or "rfnd only" cancels only its own fragment.
_POS = re.compile(
    r"both (refund|rfnd)|(refund|rfnd|refunded)\b[^.|]{0,30}?(\+|&|and)\s*(also )?(raised )?(a )?(rplc|replacement|new)|"
    r"(rplc|replacement)\s*\+\s*(refund|rfnd)|new unit|fresh unit|fresh pair|new set|new piece|sending a new|sent a new|"
    r"replacement (raised|approved|shipped|sent|issued|dispatched|unit|strap)|rplc (raised|approved|issued|dispatched|unit)|"
    r"raised rplc|also raised (rplc|replacement)|unit shipped|reshipped|re-shipped|dispatched as goodwill|"
    r"dispatched a new|a new one|released the money", re.I)
_NEG = re.compile(r"rfnd only|refund only|only (refund|rfnd)|rejected|declined|not (eligible|applicable)|explained policy|"
                  r"opted for r|preferred r|was offered earlier|offered (rplc|replacement)|asked for (rplc|replacement)|"
                  r"request(ed)? (a )?(rplc|replacement)", re.I)
_STRONG = re.compile(r"both (refund|rfnd)|refund \+ rplc|also|one-time gesture|goodwill|released the money|fresh|new unit|new set|a new one", re.I)
_VETO = re.compile(r"explained policy|rfnd only|refund only|rejected as per policy", re.I)
_SPLIT = re.compile(r"\||\n|--|(?<=[a-z0-9\)])\.\s", re.I)


def notes_mention_replacement(note):
    """True if the note says a replacement went out as well as the refund."""
    if note is None or note != note:
        return False
    note = str(note)
    hit = False
    for frag in _SPLIT.split(note):
        if _POS.search(frag) and not _NEG.search(frag):
            hit = True
            break
    # Contradictory note ("replacement dispatched ... explained policy, refund only"): trust the veto
    # unless a strong, explicit phrase also appears.
    if hit and _VETO.search(note) and not _STRONG.search(note):
        return False
    return hit


_EXPLICIT_BOTH = re.compile(
    r"both (refund|rfnd)|(refund|rfnd|refunded|money back|amount returned|credited|payment reversed|reversed the payment)"
    r"[^|]{0,60}(rplc|replacement|new unit|new set|new piece|fresh|new one|dispatched|shipped|sending)|"
    r"(rplc|replacement)\s*\+\s*(refund|rfnd)|one-time gesture|released the money", re.I)


def replacement_evidence(note, flag):
    """Strength of evidence that refund and replacement both happened on this ticket."""
    in_notes = notes_mention_replacement(note)
    if flag and in_notes:
        return "flag + notes"
    if flag:
        return "flag only"
    if in_notes:
        return "notes, explicit refund+replacement" if _EXPLICIT_BOTH.search(str(note)) else "notes, replacement only"
    return ""


def classify_text(message, note):
    """Return (label, evidence). Agent note is checked first: it is written after the
    agent resolved the issue, so it is the better evidence of what really happened."""
    note = "" if note is None or note != note else str(note)
    message = "" if message is None or message != message else str(message)
    for source, text in (("note", note), ("message", message)):
        for label, rx in _COMPILED:
            m = rx.search(text)
            if m:
                return label, f"{source}: {m.group(0)!r}"
    return "UNCLASSIFIED", ""
