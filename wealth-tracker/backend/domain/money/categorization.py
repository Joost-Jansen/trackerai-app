"""
categorization.py — the labelling engine: from a bank row to a category.

This engine was not invented anew but ported from an existing bookkeeping
setup; the parity test in backend/tests/domain/test_categorization.py holds it
to that rule by rule. The default rules below are derived from it, but only
what applies to everyone: chains and general words.

A rule is `(priority, field, pattern, direction, category)`:

    priority   lower wins. INTERNAL is at 10, so a savings transfer never ends
               up in a spending category.
    field      N  the counterparty's name
               T  the description plus the counterparty
               A  both
               P  the personal name heuristic (2-4 words, no digits, no
                  company suffix) — catches payments to friends
    direction  '' both, 'D' out (expense), 'C' in (income)

Two things without which a large part of the transactions would stay unknown:

  * **Payment processors.** With Buckaroo, Mollie, CCV* and the like the real
    shop is not in the name but in the description. Those get a second round
    against that field.
  * **Own accounts.** Money to yourself is not an expense, even when it shows
    as a debit in your bank export. Which accounts are yours is not in code
    or in a separate file but in your accounts; see own_ibans().

Sign convention, as in bank_providers/: **spending positive, income
negative.** So 'D' is a positive amount and 'C' a negative one, and that is
exactly what the direction rules expect.

Three columns for the category in bank_transactions: `category_auto` is what
this engine concludes, `category_manual` is what you decided, and the second
always wins. relabel() therefore only writes the first — updating a rule
relabels the whole history without ever overwriting a judgement.

As in database.py every function takes an explicit `conn`.
"""

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date

from domain.money import bank_transactions
from domain.money import accounts
from domain import preferences
from domain.i18n import tr
from domain.money import safe_regex


UNKNOWN = "Onbekend"

FIELDS = ("N", "T", "A", "P")
DIRECTIONS = ("", "D", "C")
TYPES = ("EXPENSE", "INCOME", "INTERNAL")

# The priority at which a transfer to an own account is recognised. Equal to
# that of the other INTERNAL rules: money to yourself must never be hijacked by
# a spending rule.
OWN_ACCOUNT_PRIORITY = 10
OWN_ACCOUNT_CATEGORY = "Eigen rekeningen"
INVESTMENT_CATEGORY = "Naar beleggen"

# A transfer between two of your own accounts is on both: out on one, in on the
# other, the same amount, the same day or shortly after. If the other side is in
# the app as a money movement (a broker's account statement), the bank row is
# not income or spending, whatever name the bank puts with it. A withdrawal at a
# broker often comes in under your own name, and then the rule for private
# persons turned it into "received from friends".
#
# Only amount and date, no names or IBANs: that works for every bank and every
# broker. Two limits against chance:
#   * a few days, enough for a weekend and a slow transfer;
#   * a minimum amount, because an account statement is full of small costs and
#     dividends, and a €3.90 Tikkie from a friend can then happen to be just as
#     large as a transaction fee. A real deposit or withdrawal is larger; for a
#     small one the normal name rule keeps applying.
REVERSAL_DAYS = 5
REVERSAL_MINIMUM = 100.0


def _without_reversals(entries: list[dict]) -> list[dict]:
    """The movements without bookings that were reversed and booked again.

    A broker sometimes books a deposit first as a reservation (+X), reverses it
    (−X) and books it again (+X) once the money is really in. That −X is not a
    withdrawal, but it looks exactly like one: on real data it got paired with
    money that came in from another own account.

    The tell is the third booking. A pair +X/−X only drops out when the same
    amount in the same direction as the first occurs *again* within
    REVERSAL_DAYS. Without that condition what *is* real dropped out too: selling
    everything (+X) and withdrawing exactly that amount (−X). Per account, only
    amount and date.
    """
    def day(m):
        return date.fromisoformat(m["date"])

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for m in entries:
        groups[(m["account_id"], round(abs(m["amount"]), 2))].append(m)

    away: set[int] = set()
    for group_name in groups.values():
        if len(group_name) < 3:
            continue
        group_name = sorted(group_name, key=lambda m: (m["date"], m["id"]))
        for a in group_name:
            if a["id"] in away:
                continue
            back = next((b for b in group_name
                          if b["id"] not in away and b["id"] != a["id"]
                          and (b["amount"] > 0) != (a["amount"] > 0)
                          and 0 <= (day(b) - day(a)).days <= REVERSAL_DAYS), None)
            if back is None:
                continue
            again = any(c["id"] not in away and c["id"] not in (a["id"], back["id"])
                          and (c["amount"] > 0) == (a["amount"] > 0)
                          and abs((day(c) - day(back)).days) <= REVERSAL_DAYS
                          for c in group_name)
            if again:
                away.update((a["id"], back["id"]))
    return [m for m in entries if m["id"] not in away]


def reversals(conn: sqlite3.Connection, rows: list[dict]) -> dict[int, str]:
    """{bank row id: category} for bank rows with a counterpart in the money
    movements of another account (account_entries).

    One to one: a movement pairs with at most one bank row, the nearest in date.
    Seven withdrawals of €10,000 on one day are seven pairs, not seven times the
    same one. Manual rows do not take part: they are not part of an export and
    need no counterpart to be right.
    """
    per_amount: dict[float, list[dict]] = defaultdict(list)
    for m in _without_reversals(accounts.load_entries(conn)):
        if abs(m["amount"]) >= REVERSAL_MINIMUM:
            per_amount[round(m["amount"], 2)].append(m)
    if not per_amount:
        return {}

    uses: set[int] = set()
    off: dict[int, str] = {}
    for row in sorted(rows, key=lambda r: (r["date"], r["id"])):
        if row.get("source") == "manual" or abs(row["amount"]) < REVERSAL_MINIMUM:
            continue
        day = date.fromisoformat(row["date"])
        # The same number in both sign conventions: an expense at the bank (positive)
        # is money the broker receives (positive), and the other way round.
        candidates = [
            (abs((date.fromisoformat(m["date"]) - day).days), m["id"], m)
            for m in per_amount.get(round(row["amount"], 2), [])
            if m["id"] not in uses
        ]
        candidates = [k for k in candidates if k[0] <= REVERSAL_DAYS]
        if not candidates:
            continue
        _distance, _id, best = min(candidates, key=lambda k: (k[0], k[1]))
        uses.add(best["id"])
        off[row["id"]] = INVESTMENT_CATEGORY if best["kind"] == "broker" else OWN_ACCOUNT_CATEGORY
    return off

# A name that matches this is a company, so not a person.
_COMPANY = re.compile(
    r"\b(B\.?V|N\.?V|LTD|GMBH|LLC|INC|SA|AB|AG|VIA|BANK|GROEP|SERVICES|STICHTING"
    r"|PAYMENT|AMSTERDAM|NLD|COM|SHOP|STORE|CAFE|BAR"
    # label() turns names into capitals, so "Trendhim ApS" or "Delftsche Studenten
    # Soci" looked like a person to the person rule. These words appear in the
    # names of companies and associations, not in those of people.
    r"|APS|V\.?O\.?F|C\.?V|SRL|SAS|BVBA|LIMITED|HOLDING|EXPLOITATIE|RETAIL|CATERING"
    r"|VERENIGING|SOCI|SOCIETEIT|STUDENTEN|CLUB|WATERBEDRIJF|PUNTEN|HOOFDREKENING"
    r"|TERUGBET|REIZIGERS|DEPOSIT)\b"
)

# Payment processors: their name says nothing about what you bought.
_PROCESSOR = re.compile(
    r"BUCKAROO|STRIPE|MOLLIE|PPRO|ADYEN|WORLDLINE|WORLDPAY|SUMUP|CCV\*|BCK\*|GOC\*|NYX\*"
    r"|PAY\.NL|MULTISAFEPAY|NUVEI|KLARNA|REVOLUT|SIX PAYMENT|MYPOS"
)


# ---------------------------------------------------------------------------
# The taxonomy and the rules, generated from financien/migratie/rules.py
# ---------------------------------------------------------------------------

# Two types deviate from the original on purpose, see the comments below. The
# parity test compares categories and not types, so it stays green.
# Money that passes through your hands but is not yours: the sailing holiday you
# advance for friends, or their share you hold until the bill comes. INTERNAL,
# so no income and no spending; net_worth.series counts what you still hold of
# it as a debt to those others, so your net worth does not jump from it.
EXCLUDE = "Niet meetellen"
GIFTS = "Giften & schenkingen"
# Words by which a gift, donation or inheritance can be recognised, in the name
# or the description. "Erven X" is how a notary pays out an inheritance; a
# tax-free gift from parents is often called exactly that.
_GIFT_PATTERN = 'SCHENKING|BELASTINGVRIJ|ERFENIS|NALATENSCHAP|\\bERVEN\\b'
STUDENT_FINANCE = "Studiefinanciering"

DEFAULT_CATEGORIES = [
    ('Inkomsten', 'Salaris', 'INCOME'),
    ('Inkomsten', 'Belasting & toeslagen', 'INCOME'),
    ('Inkomsten', 'Verkoop tweedehands', 'INCOME'),
    ('Inkomsten', 'Overige inkomsten', 'INCOME'),
    # A gift, donation or inheritance: yours, but not earned. As internal it does
    # not count as income (your savings rate stays about what you earn yourself),
    # and in your net worth it simply does — it is on your account.
    ('Inkomsten', GIFTS, 'INTERNAL'),
    # Student finance is a loan: it is a debt in your net worth and is not earned.
    # Internal for the same reason as a gift.
    ('Inkomsten', STUDENT_FINANCE, 'INTERNAL'),
    ('Wonen', 'Huur', 'EXPENSE'),
    # EXPENSE in the original. Money coming in with a minus sign in a spending
    # total makes that total useless: it can go negative. This is what it is —
    # income.
    ('Wonen', 'Huur ontvangen huisgenoten', 'INCOME'),
    ('Wonen', 'Energie & water', 'EXPENSE'),
    ('Wonen', 'Internet & telefoon', 'EXPENSE'),
    ('Wonen', 'Huis & onderhoud', 'EXPENSE'),
    ('Verzekering & zorg', 'Verzekeringen', 'EXPENSE'),
    ('Verzekering & zorg', 'Zorgkosten', 'EXPENSE'),
    ('Verzekering & zorg', 'Belasting betaald', 'EXPENSE'),
    ('Abonnementen', 'Sport abonnement', 'EXPENSE'),
    ('Abonnementen', 'Media & software', 'EXPENSE'),
    ('Abonnementen', 'Bankkosten', 'EXPENSE'),
    ('Abonnementen', 'Overige abonnementen', 'EXPENSE'),
    ('Boodschappen', 'Supermarkt', 'EXPENSE'),
    ('Boodschappen', 'Drogisterij', 'EXPENSE'),
    # Food, going out and outings belong together; holiday is large and irregular
    # enough for a group of its own; sport and hobby is something you buy, like
    # clothing. See GROUPS_SINCE.
    ('Eten & vrije tijd', 'Lunch werk', 'EXPENSE'),
    ('Eten & vrije tijd', 'Cafe & uitgaan', 'EXPENSE'),
    ('Eten & vrije tijd', 'Uit eten & bezorgen', 'EXPENSE'),
    ('Eten & vrije tijd', 'Uitjes & evenementen', 'EXPENSE'),
    ('Vervoer', 'Openbaar vervoer', 'EXPENSE'),
    ('Vervoer', 'Deelvervoer & taxi', 'EXPENSE'),
    ('Vervoer', 'Fiets', 'EXPENSE'),
    ('Vakantie', 'Vakantie', 'EXPENSE'),
    ('Shoppen', 'Kleding & schoenen', 'EXPENSE'),
    ('Shoppen', 'Sport & hobby', 'EXPENSE'),
    ('Shoppen', 'Wonen & interieur', 'EXPENSE'),
    ('Shoppen', 'Elektronica & online', 'EXPENSE'),
    ('Shoppen', 'Persoonlijke verzorging', 'EXPENSE'),
    ('Shoppen', 'Cadeaus & goede doelen', 'EXPENSE'),
    ('Vrienden & delen', 'Betaald aan vrienden', 'EXPENSE'),
    # Likewise.
    ('Vrienden & delen', 'Ontvangen van vrienden', 'INCOME'),
    ('Intern', 'Naar spaarrekening', 'INTERNAL'),
    ('Intern', 'Naar beleggen', 'INTERNAL'),
    ('Intern', 'Creditcard aflossing', 'INTERNAL'),
    ('Intern', 'Eigen rekeningen', 'INTERNAL'),
    ('Intern', 'Contant opnemen', 'INTERNAL'),
    # Money that passes through your hands but is not yours: you hold it for
    # friends, you advance something and get it back. No income and no spending; as
    # internal it counts in no total at all.
    ('Intern', 'Niet meetellen', 'INTERNAL'),
    ('Onbekend', 'Onbekend', 'EXPENSE'),
]

# The default rules: shop chains, transport companies, insurers and general
# words that mean the same for everyone. What is only right for one person — an
# employer, a landlord, a regular pub, a friend — does not belong in the code
# but in that user's own rules. You make those on the Categories screen, or with
# "Make a rule from this" on a transaction.
#
# Own accounts are not here either: they come from your accounts, see label().
DEFAULT_RULES = [
    (10, 'N', 'ORANJE SPAARREKENING|SPAARREKENING|TOP-UP VIA BUNQ|BUNQ SAVINGS', '', 'Naar spaarrekening'),
    (10, 'N', 'FLATEX|DEGIRO|COINBASE|BITVAVO|MEESMAN|BRAND NEW DAY', '', 'Naar beleggen'),
    # "ING Bank N.V. Creditcards": that is what paying off your own credit card is called.
    (10, 'N', '^CREDITCARD$|INCASSO (ING )?CREDITCARD|BETALING NAAR CREDITCARD| CREDITCARDS?$', '', 'Creditcard aflossing'),
    (10, 'N', 'GELDMAAT|ATM ', '', 'Contant opnemen'),
    # Before salary and before "received from friends": a gift from your parents
    # comes from a person, and would otherwise count as income.
    (14, 'A', _GIFT_PATTERN, 'C', GIFTS),
    (15, 'N', 'RANDSTAD|YOUNG CAPITAL|SALARY', 'C', 'Salaris'),
    # Who the employer is differs per person; that it is salary is in the
    # description, and those words are the same for everyone.
    (15, 'T', 'SALARIS|SALARY|\\bWAGE\\b|LOONSTROOK|VAKANTIEGELD|HOLIDAY ALLOWANCE', 'C', 'Salaris'),
    (15, 'N', 'BELASTINGDIENST|TOESLAGEN|GEM BELASTINGEN|WATERSCHAP', 'C', 'Belasting & toeslagen'),
    (15, 'N', 'VINTED|SELLHELP|SELLPY|MARKTPLAATS|MANGOPAY', 'C', 'Verkoop tweedehands'),
    # "Interest" is what the English ING savings export calls the interest.
    (16, 'N', 'ING PUNTEN|POSTCODE LOTERIJ|RENTE|^INTEREST$', 'C', 'Overige inkomsten'),
    # bunq pays interest weekly as "bunq Payday", from bunq itself.
    (16, 'T', 'BUNQ PAYDAY', 'C', 'Overige inkomsten'),
    (20, 'T', 'HUUR|DEEL HUUR|VASTE LASTEN', 'D', 'Huur'),
    (20, 'T', 'HUUR|VASTE LASTEN|GAS WATER LICHT', 'C', 'Huur ontvangen huisgenoten'),
    (21, 'N', 'GREENCHOICE|VATTENFALL|ENECO|ENGIE|WATERNET|VITENS|OXXIO|BUDGET ENERGIE', '', 'Energie & water'),
    (21, 'N', 'ZIGGO|KPN|VODAFONE|T-MOBILE|ODIDO|MOBIEL\\.NL|WEBSEND|LEBARA|SIMYO', '', 'Internet & telefoon'),
    (21, 'N', 'ALLESTEGENONGEDIERTE|LOODGIETER|VVE', '', 'Huis & onderhoud'),
    (22, 'N', 'LEMONADE|VINKVINK|ZILVEREN KRUIS|FBTO|CENTRAAL BEHEER|UNIVE|ACHMEA|INSHARED|DITZO|NN |AEGON', '', 'Verzekeringen'),
    (22, 'N', 'HUIDKLINIEK|TANDART|APOTHEEK|HUISARTS|FYSIO|ZORG(?!VERZ)|CZ |MENZIS|SPECSAVERS', '', 'Zorgkosten'),
    (23, 'N', 'SPORTCITY|BASIC.?FIT|FIT FOR FREE|CLASSPASS|TRAINMORE|ZWEMBAD', '', 'Sport abonnement'),
    (23, 'N', 'NETFLIX|SPOTIFY|APPLE\\.COM|APPLE MEDIA|GOOGLE|DISNEY|VIAPLAY|HBO|YOUTUBE|ADOBE|OPENAI|ANTHROPIC', '', 'Media & software'),
    (23, 'N', 'KOSTEN ORANJEPAKKET|KOSTEN .*PAKKET|BANKKOSTEN', '', 'Bankkosten'),
    (24, 'N', 'RODE KRUIS|UNICEF|GREENPEACE|ARTSEN ZONDER|WNF|GOEDE DOEL|POSTCODE LOTERIJ', 'D', 'Cadeaus & goede doelen'),
    (30, 'N', 'ALBERT HEIJN|\\bAH \\b|AH TO GO|DIRK|JUMBO|LIDL|ALDI|PLUS |VOMAR|SPAR |COOP|EKOPLAZA|SUPERMAR|MARQT|PICNIC|CRISP', '', 'Supermarkt'),
    (30, 'N', 'KRUIDVAT|ETOS|TREKPLEISTER|DA DROGIST|HOLLAND & BARRETT|IHERB', '', 'Drogisterij'),
    (35, 'N', 'SODEXO|ALBRON|COMPASS GROUP', '', 'Lunch werk'),
    (36, 'N', 'CAFE|CAFÉ|BAR |PUB|BIER|BROUWERI|KARAOKE|TABAC|CLUB|DISCO', '', 'Cafe & uitgaan'),
    (37, 'N', 'UBER ?\\* ?EATS|THUISBEZORGD|DELIVEROO|DOMINO|NEW YORK PIZZA|FEBO|SMULLERS|SUSHI|RESTAURANT|EETCAFE|BAKKER|KIOSK|HMS HOST|DALLMAYR|PORTABELLA|EPICERIE|BROODJE|LUNCH|POKE|WOK|GRILL|SNACK|KEBAB|SHOARMA', '', 'Uit eten & bezorgen'),
    (40, 'N', 'NS GROEP|NS REIZIGERS|GVB|RET |CONNEXXION|ARRIVA|OV-CHIPKAART|TRANSDEV|9292|FLIXBUS|BLABLA', '', 'Openbaar vervoer'),
    (40, 'N', 'BREEZE|FELYX|CHECK NETHERLANDS|GO SHARING|UBER|BOLT\\.EU|TAXI|GREENWHEELS|MYWHEELS|SIXT|SNAPPCAR', '', 'Deelvervoer & taxi'),
    (40, 'N', 'SWAPFIETS|FIETS|BIKE|DECATHLON.*FIETS', '', 'Fiets'),
    (45, 'N', 'LOWLANDS|PARADISO|MELKWEG|TICKETMASTER|EVENTIM|PATHE|CINEMA|MUSEUM|THEATER|FESTIVAL|VIDEOTHEEK|TICKET|ZIGGO DOME|AFAS|JAARBEURS|ESCAPE|BOWL|PADEL|GOC\\*', '', 'Uitjes & evenementen'),
    (46, 'N', 'DECATHLON|RUNNERSWORLD|INTERSPORT|PERRY|SPORT ?', '', 'Sport & hobby'),
    (47, 'N', 'TRAVELBASE|BOOKING\\.COM|AIRBNB|RYANAIR|TRANSAVIA|KLM|EASYJET|SKI|HOSTEL|HOTEL|CAMPING|SUNWEB|TUI|CORENDON', '', 'Vakantie'),
    (47, 'N', ' FRA$| ESP$| ITA$| DEU$| BEL$| AUT$| PRT$| GRC$| LUX$| GBR$| USA$| CHE$| POL$| HRV$| SWE$| DNK$| NOR$', '', 'Vakantie'),
    (50, 'N', 'ZALANDO|UNIQLO|WEEKDAY|H&M|ABOUT YOU|URBAN OUTFITTERS|END\\. CLOTHING|OMODA|ZARA|C&A|PRIMARK|MONKI|ARKET|COS |NIKE|ADIDAS|SNIPES|FOOT ?LOCKER|VAN HAREN|SCOTCH|LEVI|ALIPAY|SHEIN|TEMU', '', 'Kleding & schoenen'),
    (50, 'N', 'GAMMA|IKEA|ACTION|PRAXIS|HORNBACH|KARWEI|BLOKKER|HEMA|XENOS|LEEN BAKKER|JYSK|CASA |FLYING TIGER|KWANTUM', '', 'Wonen & interieur'),
    (50, 'N', 'COOLBLUE|BOL\\.COM|MEDIAMARKT|AMAZON|APPLE STORE|COOLBLUE|COMPUTER|COMPUTERLAND|COMPU|ALTERNATE|COMPUTER', '', 'Elektronica & online'),
    (50, 'N', 'TREATWELL|KAPSALO|KAPPER|BARBER|NAGELS|SALON|TABAKS|TABAK', '', 'Persoonlijke verzorging'),
    (51, 'N', 'POSTNL|POSTZEGEL|BLOEM|GALL|SLIJTERIJ', '', 'Cadeaus & goede doelen'),
    (15, 'N', 'BELASTINGDIENST|TOESLAGEN|GEM BELASTINGEN|WATERSCHAP|GEMEENTE', 'D', 'Belasting betaald'),
    (48, 'N', 'AUCHAN|CARREFOUR|INTERMARCHE|LE VIVIER|LECLERC|SPAR ES|MERCADONA', '', 'Vakantie'),
    (49, 'N', 'ANWB|KETTINGENENARMBANDEN|LUCARDI|PANDORA|JUWELIER', '', 'Cadeaus & goede doelen'),
    (49, 'N', 'TWEEWIELERS|RIJWIEL|BIKESHOP', '', 'Fiets'),
    (49, 'N', 'BELSIMPEL|GOMIBO|KLARNA|AMAC', '', 'Elektronica & online'),
    (49, 'N', 'VERS SHOP|VERSMARKT|SLAGERIJ|TOKO', '', 'Supermarkt'),
    (49, 'N', 'MASSAGE|SAUNA|SPA ', '', 'Persoonlijke verzorging'),
    (49, 'N', 'SPORTFONDSEN|ZWEMSCHOOL|TRIATHLON|RUN |LOOP', '', 'Sport & hobby'),
    (52, 'N', 'VINTED|MANGOPAY|SELLPY|SELLHELP', 'D', 'Kleding & schoenen'),
    (49, 'N', 'BOL\\.?COM|FONQ|ALLEKABELS|COOLBLUE|AMAC|MEDIAMARKT', '', 'Elektronica & online'),
    (49, 'N', 'OVPAY|OV-?PAY|NS STATION', '', 'Openbaar vervoer'),
    (49, 'N', 'MCDONALD|BURGER KING|KFC|SUBWAY|COFFEECOMPANY|STARBUCKS|COFFEE|BAGELS|LA PLACE|VAPIANO', '', 'Uit eten & bezorgen'),
    (49, 'N', 'TIVOLI|VREDENBURG|PARADISO|DOELEN|CARRE|CONCERT|MUZIEK', '', 'Uitjes & evenementen'),
    (49, 'N', 'KEURSLAGER|SLAGER|BAKKERIJ|GROENTE|KAAS', '', 'Supermarkt'),
    (49, 'N', 'FASHION ID|NOO\\.MA|SNIPES|ZALANDO|OTRIUM|WEHKAMP', '', 'Kleding & schoenen'),
    (49, 'N', 'TOBACCO|COFFEESHOP', '', 'Persoonlijke verzorging'),
    (80, 'T', 'TIKKIE|BETAALVERZOEK|VERZOEK|SPLIT', 'D', 'Betaald aan vrienden'),
    (80, 'T', 'TIKKIE|BETAALVERZOEK|VERZOEK|SPLIT', 'C', 'Ontvangen van vrienden'),
    (90, 'N', '^(HR|MW|DHR|MEVR)[. ]|^[A-Z]\\.[A-Z]?\\.? ?[A-Z]|VIA TIKKIE', 'D', 'Betaald aan vrienden'),
    (90, 'N', '^(HR|MW|DHR|MEVR)[. ]|^[A-Z]\\.[A-Z]?\\.? ?[A-Z]|VIA TIKKIE', 'C', 'Ontvangen van vrienden'),
    (95, 'P', 'PERSON', 'D', 'Betaald aan vrienden'),
    (95, 'P', 'PERSON', 'C', 'Ontvangen van vrienden'),
]

# Version 5: what the money was for, when the description says so.
#
# A Tikkie or a transfer to a friend is not a category but a way of paying:
# "Hotel retour", "Ubers drankjes" or "Tickets Dekmantel" says where the money
# went. These rules read the description (T), in both directions, and sit
# before the Tikkie and person rules (80-95) but after every shop name (≤ 52):
# a supermarket stays a supermarket, even if the description says "lunch". What
# you get back lands in the same category, with a minus sign: your share of the
# hotel is what you paid minus what friends paid you back.
_TARGETS = [
    (69, 'T', '\\bKADO|\\bCADEAU|\\bVERJAARDAG|\\bSINTERKLAAS|\\bSINT\\b|\\bKERSTCADEAU|\\bKERSTPAKKET|\\bBLOEMEN', '', 'Cadeaus & goede doelen'),
    (70, 'T', '\\bVAKANTIE|\\bHOTEL|\\bHOSTEL|AIRBNB|\\bCAMPING|WINTERSPORT|\\bSKI(EN|REIS|PAS|TRIP)?\\b|\\bZEIL|\\bVLUCHT|VLIEGTICKET|\\bFLIGHTS?\\b|\\bCHALET|\\bHUISJE\\b|WEEKENDJE|ROADTRIP|\\bREISJE|\\bLUSTRUM', '', 'Vakantie'),
    (71, 'T', '\\bDRANK|\\bDRINKS?\\b|\\bBIER|\\bBORREL|\\bKROEG|\\bWIJN(TJE)?S?\\b|\\bSHOTS?\\b|\\bFEEST|\\bUITGAAN|\\bRONDJE', '', 'Cafe & uitgaan'),
    (72, 'T', '\\bETEN\\b|\\bETENTJE|\\bAVONDETEN|\\bDINER|\\bDINNER|\\bLUNCH|\\bPIZZA|\\bSUSHI|\\bBURGER|\\bRESTAURANT|\\bBBQ\\b|\\bBARBECUE|\\bONTBIJT|\\bBRUNCH|\\bTAKEAWAY|\\bFRIET|\\bSHOARMA|\\bKEBAB|\\bDONER|\\bMAALTIJD', '', 'Uit eten & bezorgen'),
    (72, 'T', '\\bTICKETS?\\b|\\bKAARTJES?\\b|\\bFESTIVAL|\\bCONCERT|\\bBIOS(COOP)?\\b|\\bMUSEUM|\\bTHEATER|\\bVOORSTELLING|\\bESCAPE ?ROOM|\\bBOWLEN|\\bKARTEN|\\bPADEL|\\bLASERGAME', '', 'Uitjes & evenementen'),
    (73, 'T', '\\bKLEDING|\\bKLEREN|\\bSCHOENEN|\\bSNEAKERS|\\bJAS(JE)?\\b|\\bTRUI|\\bBROEK|\\bT-?SHIRT|\\bJURK|\\bOUTFIT|\\bKOSTUUM', '', 'Kleding & schoenen'),
    (73, 'T', '\\bBOODSCHAPPEN|\\bSUPERMARKT', '', 'Supermarkt'),
    (74, 'T', '\\bSPORT|\\bVOETBAL|\\bTENNIS|\\bHOCKEY|\\bZWEMMEN|\\bKLIMMEN|\\bBOULDER|\\bSQUASH', '', 'Sport & hobby'),
    (74, 'T', '\\bOV\\b|\\bTREIN|\\bTRAM\\b|\\bMETRO\\b|\\bOV-?CHIP', '', 'Openbaar vervoer'),
    (75, 'T', '\\bUBERS?\\b|\\bTAXI|\\bBOLT\\b', '', 'Deelvervoer & taxi'),
]

# Country codes with which ING ends a card payment abroad, besides the European
# ones in the holiday rule above. Without Ireland, Malta and Cyprus: Revolut and
# many online services invoice from there.
_COUNTRIES = ('IDN|THA|VNM|KHM|LAO|MYS|SGP|PHL|IND|LKA|NPL|JPN|KOR|CHN|HKG|TWN|AUS|NZL|CAN|MEX'
           '|BRA|ARG|PER|COL|CHL|CRI|CUB|DOM|ZAF|MAR|EGY|TUN|TUR|ISR|JOR|ARE|QAT|ISL|FIN'
           '|CZE|SVK|SVN|HUN|ROU|BGR|SRB|MNE|ALB|MKD|BIH|EST|LVA|LTU|UKR|GEO|TZA|KEN|MDV')

_NEW_IN_5 = _TARGETS + [
    # A transfer to your own savings account is in your name ("Hr J de Vries"), and
    # the savings rule above only looks at the name. The description does say it:
    # "To Oranje spaarrekening D12345678".
    (10, 'T', 'ORANJE SPAARREKENING|\\b(TO|FROM|NAAR|VAN) (\\w+ )?SPAARREKENING', '', 'Naar spaarrekening'),
    (10, 'N', 'KRAKEN|PAYWARD|BITONIC|\\bBLOX\\b|\\bFINST\\b|TRADE REPUBLIC|SCALABLE CAPITAL|\\bBUX\\b', '', 'Naar beleggen'),
    (10, 'A', 'TRANSFER TO CREDIT ?CARD|CREDIT CARD MORE', '', 'Creditcard aflossing'),
    (10, 'N', 'ING DEPOSIT|CASH DEPOSIT|STORTING CONTANT', '', 'Contant opnemen'),
    (15, 'T', 'LOONSLIP|LOONSPECIFICATIE|SALARISSTROOK|PAYSLIP', 'C', 'Salaris'),
    (15, 'N', '^DUO\\b|DIENST UITVOERING ONDERWIJS', 'C', STUDENT_FINANCE),
    (15, 'T', 'STUDENT_FINANCE', 'C', STUDENT_FINANCE),
    # Not the word "cashback" in the description: at ING that is also what a normal
    # refund at the till is called, and that belongs with the shop.
    (16, 'N', 'CASHBACK', 'C', 'Overige inkomsten'),
    (16, 'T', 'GEFELICITEERD.*TERUGGEW', 'C', 'Overige inkomsten'),
    (21, 'N', 'EVIDES|DUNEA|BRABANT WATER|\\bPWN\\b|\\bWML\\b|WATERBEDRIJF|ESSENT|ENERGIEDIRECT|UNITED CONSUMERS|FRANK ENERGIE|TIBBER|ZONNEPLAN|VANDEBRON|ENERGYZERO|PURE ENERGIE', '', 'Energie & water'),
    (23, 'N', 'RSG GROUP|MCFIT|GOLD.?S GYM|JOHN REED|ANYTIME FITNESS|FITNESS|SPORTSCHOOL|\\bGYM\\b', '', 'Sport abonnement'),
    (23, 'N', '^APPLE$|VIDEOLAND|STUDEERSNEL|NPO PLUS|STORYTEL|AUDIBLE|MICROSOFT|DROPBOX|PATREON', '', 'Media & software'),
    (23, 'N', 'RENTSLAM|KAMERNET|PARARIUS|HUURWONINGEN', '', 'Overige abonnementen'),
    (30, 'N', '\\bFLINK\\b|GETIR|GORILLAS|\\bZAPP\\b', '', 'Supermarkt'),
    (35, 'N', 'BEDRIJFSREST|CIRFOOD|ELSENDOORN|EUREST|KANTINE', '', 'Lunch werk'),
    # Coffee and snack machines paid in Son en Breugel. After the shops: there is
    # an IKEA there too.
    (55, 'N', 'SON EN BREUG|\\bSON NLD$', '', 'Lunch werk'),
    (36, 'N', 'SOCIETEIT|SOCIËTEIT|STUDENTEN ?SOC|STUDENTENVERENIGING|STUDENTENCORPS|DISPUUT|NACHTCLUB', '', 'Cafe & uitgaan'),
    (37, 'N', 'TAKEAWAY|JUST EAT|HMS ?HOST|\\bRELAY\\b|DONER|GELATO|IJSSALON|FOODHALL|FOOD HALL|BAGEL|FALAFEL|RAMEN|TACO|BURRITO', '', 'Uit eten & bezorgen'),
    (40, 'N', '^NSR |NS ?AUTOMAAT|NS INTERNATIONAL|QBUZZ|\\bEBS\\b|\\bHTM\\b|KEOLIS|\\bRNET\\b|EUROSTAR|THALYS', '', 'Openbaar vervoer'),
    (40, 'N', 'GO ?SHARING|DONKEY REPUBLIC|\\bLIME\\b|\\bTIER\\b|\\bDOTT\\b|GRAB\\*|GOJEK|\\bLYFT\\b|CABIFY|FREE ?NOW', '', 'Deelvervoer & taxi'),
    (45, 'N', 'PAYLOGIC|DEKMANTEL|WETICKET|WEEZEVENT|YOURTICKETPROVIDER|EVENTBRITE|TICKETSWAP|SEE ?TICKETS|GROUPON', '', 'Uitjes & evenementen'),
    (46, 'N', 'SQUASH|KLIMHAL|BOULDER|TENNIS|HOCKEY|GOLF', '', 'Sport & hobby'),
    (47, 'N', 'KIWI\\.COM|SKYSCANNER|EXPEDIA|HOTELS\\.COM|AGODA|VUELING|WIZZ|LUFTHANSA|EUROWINGS|HOSTELWORLD|GETYOURGUIDE|VIATOR', '', 'Vakantie'),
    (47, 'N', f' ({_COUNTRIES})$', '', 'Vakantie'),
    # For a payment in a foreign currency bunq puts the rate in the description:
    # "120000.00 IDR, 1 IDR = 0.00005 EUR". Not dollars: those are often online.
    (48, 'T', '\\d ((?!EUR|USD)[A-Z]{3}), 1 \\1 = ', '', 'Vakantie'),
    (50, 'N', 'CARHARTT|\\bH ?& ?M\\b|\\bH +M \\d|BIJENKORF|ASOS|NAPAPIJRI|FRESHCOTTON|BLUE TOMATO|TRENDHIM|ABOUT ?YOU|PULL ?& ?BEAR|BERSHKA|\\bMANGO\\b|NORTH FACE|PATAGONIA|REEBOK|\\bPUMA\\b|NEW BALANCE|ABERCROMBIE|HOLLISTER|TOMMY HILFIGER|RALPH LAUREN|G-STAR|SUITSUPPLY|JACK ?& ?JONES|WE FASHION|ZEEMAN|THE STING|\\bBEVER\\b|JD SPORTS|SEVENSTORE|STRADIVARIUS|MASSIMO DUTTI', '', 'Kleding & schoenen'),
    (50, 'N', '\\bG2A\\b|STEAM|PLAYSTATION|NINTENDO|XBOX|ALIEXPRESS|\\bETSY\\b|\\bEBAY\\b', '', 'Elektronica & online'),
    (50, 'N', 'ALLTRICKS|BIKE ?TOTAAL', '', 'Fiets'),
    # An old Tikkie: "ABN AMRO Bank NV", with the friend who was paid and their IBAN
    # only in the description, after two long reference numbers.
    (80, 'A', 'ABN AMRO BANK N\\.?V\\.?.*\\b\\d{12} \\d{16}\\b', 'D', 'Betaald aan vrienden'),
    (80, 'A', 'ABN AMRO BANK N\\.?V\\.?.*\\b\\d{12} \\d{16}\\b', 'C', 'Ontvangen van vrienden'),
]
DEFAULT_RULES += _NEW_IN_5

# Default rules that were added later, per version. A new user gets
# DEFAULT_RULES in one go; someone who already had their rules gets, through
# seed(), only what was added since their version, once. Once, so a rule you
# throw away afterwards stays thrown away — just like with the first seeding.
#
# Only additions, never changes: a pattern you sharpened yourself must not
# quietly jump back. Where an existing pattern was broadened, only the new part
# is here, as a rule of its own.
DEFAULT_RULES_VERSION = 7
# Categories that later moved to another group, per version: (category, old
# group, new group). Only when the category is still in that old group: what you
# moved to another group yourself stays there.
GROUPS_SINCE = {
    6: [
        ('Lunch werk', 'Eten & drinken', 'Eten & vrije tijd'),
        ('Cafe & uitgaan', 'Eten & drinken', 'Eten & vrije tijd'),
        ('Uit eten & bezorgen', 'Eten & drinken', 'Eten & vrije tijd'),
        ('Uitjes & evenementen', 'Vrije tijd', 'Eten & vrije tijd'),
        ('Sport & hobby', 'Vrije tijd', 'Eten & vrije tijd'),
        ('Vakantie', 'Vrije tijd', 'Vakantie'),
    ],
    7: [('Sport & hobby', 'Eten & vrije tijd', 'Shoppen')],
}
# Categories that were added later, same agreement: once, by name.
CATEGORIES_SINCE = {
    3: [('Intern', 'Niet meetellen', 'INTERNAL')],
    4: [('Inkomsten', GIFTS, 'INTERNAL')],
    5: [('Inkomsten', STUDENT_FINANCE, 'INTERNAL')],
}
RULES_SINCE = {
    5: _NEW_IN_5,
    4: [(14, 'A', _GIFT_PATTERN, 'C', GIFTS)],
    2: [
        (10, 'N', ' CREDITCARDS?$', '', 'Creditcard aflossing'),
        (15, 'T', 'SALARIS|SALARY|\\bWAGE\\b|LOONSTROOK|VAKANTIEGELD|HOLIDAY ALLOWANCE', 'C', 'Salaris'),
        (16, 'N', '^INTEREST$', 'C', 'Overige inkomsten'),
        (16, 'T', 'BUNQ PAYDAY', 'C', 'Overige inkomsten'),
    ],
}
_VERSION_KEY = "default_rules_version"


def _read_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_VERSION_KEY,)).fetchone()
    try:
        # Without a setting: from before there were versions, so the first set.
        return int(row["value"]) if row else 1
    except (TypeError, ValueError):
        return 1


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 (_VERSION_KEY, str(version)))


def _update_default_rules(conn: sqlite3.Connection) -> int:
    """Adds the default rules that were added since this user's version. Returns the
    number of new rules.
    """
    version = _read_version(conn)
    if version >= DEFAULT_RULES_VERSION:
        return 0
    existing = {(r["field"], r["pattern"], r["direction"], r["category"])
                for r in load_rules(conn, only_active=False)}
    # If you gave a default category another name, a new default rule points to
    # your name, not to one that no longer exists.
    renamed = _renamed(conn)
    new = [
        (priority, field, pattern, direction, renamed.get(category, category))
        for v in range(version + 1, DEFAULT_RULES_VERSION + 1)
        for priority, field, pattern, direction, category in RULES_SINCE.get(v, [])
        if (field, pattern, direction, renamed.get(category, category)) not in existing
    ]
    conn.executemany(
        "INSERT INTO rules (priority, field, pattern, direction, category) VALUES (?, ?, ?, ?, ?)",
        new,
    )
    existing_categories = {c["name"] for c in load_categories(conn)}
    sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM categories").fetchone()[0]
    for v in range(version + 1, DEFAULT_RULES_VERSION + 1):
        for group_name, name, type_ in CATEGORIES_SINCE.get(v, []):
            if name not in existing_categories:
                sort_order += 1
                conn.execute("INSERT INTO categories (group_name, name, type, sort_order) VALUES (?, ?, ?, ?)",
                             (group_name, name, type_, sort_order))
        for name, old_group, new_group in GROUPS_SINCE.get(v, []):
            conn.execute("UPDATE categories SET group_name = ? WHERE name = ? AND group_name = ?",
                         (new_group, renamed.get(name, name), old_group))
    _budgets_after_move(conn)
    clean_up_rules(conn)
    _set_version(conn, DEFAULT_RULES_VERSION)
    conn.commit()
    return len(new)


def clean_up_rules(conn: sqlite3.Connection) -> int:
    """Throws away rules that cannot do anything. Returns the number.

    * **a rule to Onbekend** — "I don't know" is not a category, and such a rule
      held back everything after it: three times "Stichting Mollie Payments →
      Onbekend" never let "Travelbase via Stichting Mollie" reach the holiday
      rule;
    * **a duplicate rule** — the same field, pattern, direction and category. The
      first (by priority) stays, and an active one goes before a disabled one.
    """
    away, seen = [], set()
    for r in sorted(load_rules(conn, only_active=False),
                    key=lambda r: (not r["active"], r["priority"], r["id"])):
        key = (r["field"], r["pattern"], r["direction"], r["category"])
        if r["category"] == UNKNOWN or key in seen:
            away.append((r["id"],))
        seen.add(key)
    conn.executemany("DELETE FROM rules WHERE id = ?", away)
    conn.commit()
    return len(away)


DEFAULT_CATEGORIES_IF_DICTS = [
    {"group_name": g, "name": n, "type": t, "sort_order": i}
    for i, (g, n, t) in enumerate(DEFAULT_CATEGORIES)
]



# ---------------------------------------------------------------------------
# Seeding and managing
# ---------------------------------------------------------------------------

def seed(conn: sqlite3.Connection) -> tuple[int, int]:
    """Sets up the default taxonomy and rules, but only if there is nothing yet.

    Only if there is nothing yet, because this runs on every init: a rule you
    threw away must stay thrown away, and a pattern you sharpened must not jump
    back to the factory setting on every start.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS n FROM categories")
    categories = 0
    if cursor.fetchone()["n"] == 0:
        cursor.executemany(
            "INSERT INTO categories (group_name, name, type, sort_order) VALUES (?, ?, ?, ?)",
            [(g, n, t, i) for i, (g, n, t) in enumerate(DEFAULT_CATEGORIES)],
        )
        categories = len(DEFAULT_CATEGORIES)

    cursor.execute("SELECT COUNT(*) AS n FROM rules")
    rules = 0
    if cursor.fetchone()["n"] == 0:
        cursor.executemany(
            "INSERT INTO rules (priority, field, pattern, direction, category) "
            "VALUES (?, ?, ?, ?, ?)",
            list(DEFAULT_RULES),
        )
        rules = len(DEFAULT_RULES)
        _set_version(conn, DEFAULT_RULES_VERSION)
        conn.commit()
    else:
        outdated = _read_version(conn) < DEFAULT_RULES_VERSION
        rules = _update_default_rules(conn)
        if outdated:
            # A new default rule also applies to what you already had: last year's gift was
            # "received from friends" and counted as income, and a rule that only relabels
            # unknown rows would never have seen it. Also without a new rule, because a new
            # version can also make the engine itself smarter. Once per version; what you
            # set by hand stays.
            relabel(conn, everything=True)

    # Without an API key on the server no AI labels, also not from before: they fall
    # back right away to what the rules find (relabel goes over them).
    if not os.environ.get("ANTHROPIC_API_KEY") and conn.execute(
        "SELECT 1 FROM bank_transactions WHERE category_source = 'ai' LIMIT 1"
    ).fetchone():
        relabel(conn)

    conn.commit()
    return categories, rules


def load_categories(conn: sqlite3.Connection) -> list[dict]:
    """In order. `is_fixed`: the app itself relies on that name; see FIXED_CATEGORIES."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories ORDER BY sort_order ASC, name ASC")
    return [dict(row) | {"is_fixed": row["name"] in FIXED_CATEGORIES,
                         "type_locked": row["name"] in TYPE_LOCKED,
                         "role": role_of(row["name"], row["type"])} for row in cursor.fetchall()]


def load_rules(conn: sqlite3.Connection, *, only_active: bool = True) -> list[dict]:
    """Rules by priority; the first that matches wins."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM rules"
        + (" WHERE active = 1" if only_active else "")
        + " ORDER BY priority ASC, id ASC"
    )
    return [dict(row) for row in cursor.fetchall()]


def make_category(conn: sqlite3.Connection, *, group_name: str, name: str, type: str) -> int:
    if type not in TYPES:
        raise ValueError(tr("Unknown type: {0}. Choose from: {1}", repr(type), ', '.join(TYPES)))
    name = (name or "").strip()
    if not name:
        raise ValueError(tr("A category must have a name."))

    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS v FROM categories")
    cursor.execute(
        "INSERT INTO categories (group_name, name, type, sort_order) VALUES (?, ?, ?, ?)",
        (group_name, name, type, cursor.fetchone()["v"]),
    )
    conn.commit()
    return cursor.lastrowid


def make_rule(conn: sqlite3.Connection, *, priority: int, field: str, pattern: str,
               direction: str, category: str) -> int:
    if field not in FIELDS:
        raise ValueError(tr("Unknown field: {0}. Choose from: {1}", repr(field), ', '.join(FIELDS)))
    if direction not in DIRECTIONS:
        raise ValueError(tr("Unknown direction: {0}", repr(direction)))
    # A broken pattern would otherwise only fall over when relabelling, and then it
    # is no longer clear which of the sixty rules it was. A pattern that could
    # backtrack for minutes (ReDoS) is refused too: see safe_regex.py.
    safe_regex.check(pattern)
    if category == UNKNOWN:
        # See clean_up_rules: such a rule labels nothing and holds back better ones.
        raise ValueError(tr("A rule must point to a category, not to Onbekend."))
    # The same rule again is not a second rule; you get the existing one back.
    for r in load_rules(conn, only_active=False):
        if (r["field"], r["pattern"], r["direction"], r["category"]) == (field, pattern, direction, category):
            return r["id"]

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO rules (priority, field, pattern, direction, category) VALUES (?, ?, ?, ?, ?)",
        (priority, field, pattern, direction, category),
    )
    conn.commit()
    return cursor.lastrowid


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.cursor().execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()


def delete_category(conn: sqlite3.Connection, category_id: int) -> None:
    conn.cursor().execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()


def _reorder(conn: sqlite3.Connection) -> None:
    """Keeps the categories of one main category together: the groups in the order
    in which they first appear, within them their own order.
    """
    rows = conn.execute("SELECT id, group_name, sort_order FROM categories ORDER BY sort_order, id").fetchall()
    first: dict[str, int] = {}
    for r in rows:
        first.setdefault(r["group_name"], len(first))
    ordered = sorted(rows, key=lambda r: (first[r["group_name"]], r["sort_order"], r["id"]))
    conn.executemany("UPDATE categories SET sort_order = ? WHERE id = ?",
                     [(i, r["id"]) for i, r in enumerate(ordered)])


def _with_budget(conn: sqlite3.Connection, old: str, new: str) -> None:
    """A budget belongs to a main category, by name. If that name goes, the budget
    goes along; if two merge, their budgets add up.
    """
    if old == new:
        return
    row = conn.execute("SELECT amount FROM budgets WHERE group_name = ?", (old,)).fetchone()
    if row is None:
        return
    conn.execute("INSERT INTO budgets (group_name, amount) VALUES (?, ?) "
                 "ON CONFLICT(group_name) DO UPDATE SET amount = budgets.amount + excluded.amount", (new, row["amount"]))
    conn.execute("DELETE FROM budgets WHERE group_name = ?", (old,))


def _budgets_after_move(conn: sqlite3.Connection) -> None:
    """A budget on a main category that a new default layout left empty goes to
    where most of its categories went — also for earlier layouts (version 6 left
    them hanging).
    """
    existing = {r["group_name"] for r in conn.execute("SELECT DISTINCT group_name FROM categories")}
    dest: dict[str, Counter] = defaultdict(Counter)
    for modifications in GROUPS_SINCE.values():
        for _name, old, new in modifications:
            dest[old][new] += 1
    for old, counter in dest.items():
        if old in existing:
            continue
        target, seen = counter.most_common(1)[0][0], {old}
        while target not in existing and target in dest and target not in seen:
            seen.add(target)
            target = dest[target].most_common(1)[0][0]
        if target in existing:
            _with_budget(conn, old, target)


def role_of(name: str, type_: str) -> str:
    """What a category does on Net worth, a step finer than its type.

    Spending and income make up Saved; everything internal lands in Bank & cash,
    but some internal categories have a known other side: money to your broker
    (it reappears in investments), a repayment (it reappears in debt), money
    between your own accounts (net zero), and money of others. The page shows
    this so an internal category is not just "Bank & cash"."""
    if type_ == "EXPENSE":
        return "spending"
    if type_ == "INCOME":
        return "income"
    if name == INVESTMENT_CATEGORY:
        return "investments"
    if name == "Creditcard aflossing":
        return "debt"
    if name in (OWN_ACCOUNT_CATEGORY, "Naar spaarrekening"):
        return "own"
    if name == EXCLUDE:
        return "others"
    return "bank"


def set_type(conn: sqlite3.Connection, category_id: int, type_: str) -> None:
    """Whether a category counts as spending, income or nowhere (internal).

    That is also where it lands on Net worth: spending and income in Saved,
    internal in Bank & cash. The type is read through the view at query time,
    so every total follows at once; no relabelling needed."""
    if type_ not in TYPES:
        raise ValueError(tr("Unknown type: {0}.", type_))
    row = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise KeyError(category_id)
    if row["name"] in TYPE_LOCKED:
        raise ValueError(tr("The app relies on how “{0}” counts; it can't be changed.", row["name"]))
    conn.execute("UPDATE categories SET type = ? WHERE id = ?", (type_, category_id))
    conn.commit()


def move_category(conn: sqlite3.Connection, category_id: int, group_name: str) -> None:
    """Moves a category to another main category — or a new one, if that name does
    not exist yet. At the end of an existing group; a new group comes where the
    category was. Labels and rules point to the category, not to the group, so
    they simply stay right.
    """
    group_name = (group_name or "").strip()
    if not group_name:
        raise ValueError(tr("A main category must have a name."))
    row = conn.execute("SELECT name, group_name FROM categories WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise KeyError(category_id)
    if row["name"] == UNKNOWN:
        raise ValueError(tr("Onbekend stays where it is."))
    last = conn.execute("SELECT MAX(sort_order) FROM categories WHERE group_name = ? AND id != ?",
                           (group_name, category_id)).fetchone()[0]
    if last is None:
        conn.execute("UPDATE categories SET group_name = ? WHERE id = ?", (group_name, category_id))
    else:
        conn.execute("UPDATE categories SET group_name = ?, sort_order = ? WHERE id = ?", (group_name, last + 0.5, category_id))
    # If this was the last one of its old main category, the budget goes along.
    if not conn.execute("SELECT 1 FROM categories WHERE group_name = ?", (row["group_name"],)).fetchone():
        _with_budget(conn, row["group_name"], group_name)
    _reorder(conn)
    conn.commit()


_RENAMED_KEY = "category_renamed"


def _renamed(conn: sqlite3.Connection) -> dict[str, str]:
    """Which category you gave another name: original name → current."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_RENAMED_KEY,)).fetchone()
    try:
        value = json.loads(row["value"]) if row else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# Tables and columns that name a category by name.
_NAME_COLUMNS = (
    ("categories", "name"),
    ("bank_transactions", "category_auto"),
    ("bank_transactions", "category_manual"),
    ("rules", "category"),
    ("ai_suggestions", "category"),
    ("ai_checks", "category"),
    ("ai_checks", "current"),
    ("rule_suggestions", "category"),
)


def rename_category(conn: sqlite3.Connection, category_id: int, name: str) -> str:
    """Gives a category another name. Transactions, rules and suggestions name their
    category by name, so they go along in one go. Names the app itself relies on
    (FIXED_CATEGORIES) stay, and two categories with the same name are not
    possible.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError(tr("A category must have a name."))
    row = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise KeyError(category_id)
    old = row["name"]
    if old == name:
        return name
    if old in FIXED_CATEGORIES:
        raise ValueError(tr("The app itself uses ‘{0}’; that name stays.", old))
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise ValueError(tr("There is already a category ‘{0}’.", name))
    for table, column in _NAME_COLUMNS:
        conn.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (name, old))
    # Remember it, also in a chain (A → B → C), for later default rules.
    renamed = {k: (name if v == old else v) for k, v in _renamed(conn).items()}
    renamed.setdefault(old, name)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 (_RENAMED_KEY, json.dumps(renamed, ensure_ascii=False)))
    conn.commit()
    return name


def rename_group(conn: sqlite3.Connection, old: str, new: str) -> int:
    """Gives a main category another name. If the new name already exists, the two
    merge. Returns the number of categories that went along.
    """
    new = (new or "").strip()
    if not new:
        raise ValueError(tr("A main category must have a name."))
    cursor = conn.execute("UPDATE categories SET group_name = ? WHERE group_name = ?", (new, old))
    if cursor.rowcount == 0:
        raise KeyError(old)
    _with_budget(conn, old, new)
    _reorder(conn)
    conn.commit()
    return cursor.rowcount


def own_ibans(conn: sqlite3.Connection) -> set[str]:
    """The IBANs of your own accounts — by which 'internal' is recognised.

    From the accounts and not from a separate file: an account you add is at once
    also an account to which transfers are not spending.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT iban FROM accounts WHERE iban IS NOT NULL")
    return {row["iban"] for row in cursor.fetchall()}


def own_numbers(conn: sqlite3.Connection) -> dict[int, set[str]]:
    """Per own account the numbers by which it can be recognised in a description:
    the IBAN, and the account number of a savings account without an IBAN
    ("D12345678"). Shorter than eight characters does not count: that easily
    appears in a reference.
    """
    off = {}
    for r in conn.execute("SELECT id, iban, external_id FROM accounts"):
        candidates = (accounts.normalise_iban(r["iban"]),
                      re.sub(r"\s+", "", r["external_id"] or "").upper())
        off[r["id"]] = {n for n in candidates if n and len(n) >= 8}
    return off


def names_own_account(description: str | None, numbers: set[str]) -> bool:
    """Is one of these numbers in the description? Spaces do not count: an IBAN also
    appears there in groups of four.
    """
    if not numbers:
        return False
    text = re.sub(r"\s+", "", (description or "").upper())
    return any(n in text for n in numbers)


# ---------------------------------------------------------------------------
# Learning from your own labels
# ---------------------------------------------------------------------------
#
# After the rules, before Claude: what you already labelled yourself for the same
# counterparty. Label one payment at "Sissi's" as Cafe, and the other three
# follow. It looks at the counterparty's IBAN, and otherwise at the name without
# digits (so "Bedrijfsrest. 7045 DELFT" and "7047 DELFT" are the same).

FRIENDS = ("Betaald aan vrienden", "Ontvangen van vrienden")
# Names the app itself relies on — the salary month, money between your own
# accounts, exclude, friends, gifts. These keep their names.
FIXED_CATEGORIES = frozenset({
    UNKNOWN, "Salaris", OWN_ACCOUNT_CATEGORY, "Naar spaarrekening", INVESTMENT_CATEGORY,
    "Creditcard aflossing", EXCLUDE, GIFTS, STUDENT_FINANCE, *FRIENDS,
})
# Categories whose *type* the app relies on, not only their name: money between
# your own accounts and to investments must stay internal, salary must stay
# income (the salary month looks for it), Onbekend is what has no category.
# Every other category's type is the user's to choose (set_type). That includes
# Creditcard aflossing: without the card's own purchases in the app, the
# repayment is the only trace of that spending, so it may count as spending.
TYPE_LOCKED = frozenset({
    UNKNOWN, "Salaris", OWN_ACCOUNT_CATEGORY, "Naar spaarrekening", INVESTMENT_CATEGORY,
    EXCLUDE,
})
TYPES = ("EXPENSE", "INCOME", "INTERNAL")
# How certain a suggestion from Claude must be to take it over; ai_labelling.py.
AI_THRESHOLD = 0.8
# One-off by nature: that you excluded your friends' sailing holiday says
# nothing about their next payment.
_NOT_LEARN = (UNKNOWN, EXCLUDE, GIFTS)
# Behind a Tikkie or payment processor there is someone else every time, even
# behind the same IBAN.
_NO_COUNTERPARTY = re.compile(r"TIKKIE|BETAALVERZOEK|WIEBETAALTWAT")


def learn_keys(name: str | None, counterparty_iban: str | None) -> list[str]:
    name = (name or "").upper()
    if _PROCESSOR.search(name) or _NO_COUNTERPARTY.search(name):
        return []
    keys = []
    iban = accounts.normalise_iban(counterparty_iban)
    if iban:
        keys.append("iban:" + iban)
    words = re.sub(r"[^A-Z ]+", " ", name).split()
    # The country code with which ING ends a card payment ("… AMSTERDAM NLD").
    if len(words) > 2 and len(words[-1]) == 3:
        words = words[:-1]
    if len(" ".join(words)) >= 4:
        keys.append("naam:" + " ".join(words))
    return keys


def learned(conn: sqlite3.Connection) -> dict[str, tuple[str, int, int]]:
    """Per counterparty: (most chosen category, how often, out of how many) from your
    own labels.
    """
    tellers: dict = defaultdict(lambda: defaultdict(int))
    for r in conn.execute("SELECT name, counterparty_iban, category_manual FROM bank_transactions "
                          "WHERE category_manual IS NOT NULL"):
        if r["category_manual"] in _NOT_LEARN:
            continue
        for key in learn_keys(r["name"], r["counterparty_iban"]):
            tellers[key][r["category_manual"]] += 1
    off = {}
    for key, counter in tellers.items():
        category, n = max(counter.items(), key=lambda kv: kv[1])
        off[key] = (category, n, sum(counter.values()))
    return off


def from_learned(learnt: dict, *, name: str | None, counterparty_iban: str | None, weak: bool) -> str | None:
    """The category you use yourself for this counterparty, or None.

    For something without a category a clear majority is enough. A payment
    labelled as "friends" it only overwrites if you labelled that person at least
    three times, and the same each time: one dinner with a friend does not turn
    all their Tikkies into eating out.
    """
    for key in learn_keys(name, counterparty_iban):
        if key not in learnt:
            continue
        category, n, total = learnt[key]
        if (n == total and n >= 3) if weak else (n / total >= 2 / 3):
            return category
    return None


# Words that are in every transfer and say nothing about what for.
_NOISE = re.compile(r"\b(NAME|DESCRIPTION|NAAM|OMSCHRIJVING|IBAN|BIC|TIKKIE|ID|VIA|VAN|AAN|BETALING|"
                   r"BETAALVERZOEK|VALUE|DATE|TIME|DATUM|KENMERK|REFERENTIE|EUR|HR|MW|DHR|MEVR)\b")


def has_target_text(name: str | None, description: str | None) -> bool:
    """Does the description say anything other than who it was? Without that a
    payment to a friend cannot be guessed — not by Claude either. "Betaling van GH
    Dekker" or a Tikkie with only reference numbers: no. "Tapas": yes.
    """
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", " ", (description or "").upper())
    for word in set(re.findall(r"[A-Z]+", (name or "").upper())):
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"[^A-Z]+", " ", _NOISE.sub(" ", text))
    return any(len(w) >= 3 for w in text.split())


def ai_suggestions(conn: sqlite3.Connection) -> dict[int, str]:
    """What Claude suggested with enough certainty — only if it may help and the
    server has an API key. If you turn it off, or the key disappears, everything
    it labelled falls back in the next round.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    value = preferences.read(conn, "ai_labelling")
    if not (value and value.get("on")):
        return {}
    # Nothing internal: saving, own accounts and "exclude" follow from your accounts
    # or are your choice, not something a model can see. And never an income
    # category on an expense (also not from earlier rounds).
    return {r["transaction_id"]: r["category"] for r in conn.execute(
        "SELECT a.transaction_id, a.category FROM ai_suggestions a "
        "JOIN categories c ON c.name = a.category "
        "JOIN bank_transactions t ON t.id = a.transaction_id "
        "WHERE a.confidence >= ? AND a.category != ? AND c.type != 'INTERNAL' "
        "AND NOT (c.type = 'INCOME' AND t.amount > 0)",
        (AI_THRESHOLD, UNKNOWN))}


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------

def is_person(name: str) -> bool:
    """Does this look like a person and not like a company?

    Two to four words, no digits, no company suffix, and everything in capitals —
    that is how banks write a private counterparty. It is the last rule that runs
    (priority 95), so it only has to catch what belongs nowhere else.
    """
    text = (name or "").strip()
    if not text or any(character.isdigit() for character in text):
        return False
    if _COMPANY.search(text):
        return False
    words = [w for w in re.split(r"[ .]+", text) if w]
    return 2 <= len(words) <= 4 and all(
        re.fullmatch(r"[A-Z'À-Ü-]+", w) for w in words
    )


def _search(rules, *, name, memo, direction):
    everything = f"{name} {memo}"
    for rule in rules:
        if rule["direction"] and rule["direction"] != direction:
            continue
        # A rule to Onbekend knows nothing, and must not hold back better rules after
        # it. See clean_up_rules.
        if rule["category"] == UNKNOWN:
            continue
        if rule["field"] == "P":
            if is_person(name):
                return rule["category"], rule["priority"]
            continue
        target = name if rule["field"] == "N" else (memo if rule["field"] == "T" else everything)
        # Case insensitive, because the haystack above has already been turned into
        # capitals. The fifty-nine shipped patterns are in capitals themselves, so for
        # those nothing changes — but a pattern you type yourself or that comes from
        # "Make a rule from this" takes over the counterparty's spelling, and "bunq"
        # would then never find "BUNQ". Silently doing nothing is the worst outcome
        # here: the rule is there, it looks fine, and it labels nothing.
        # With a timeout: see safe_regex.py.
        if safe_regex.search(rule["pattern"], target):
            return rule["category"], rule["priority"]
    return None


def label(
    rules: list[dict],
    *,
    name: str,
    description: str = "",
    counterparty_iban: str | None = None,
    amount: float = 0.0,
    own_ibans: set[str] | None = None,
    own_numbers: set[str] | None = None,
) -> tuple[str, int]:
    """Returns (category, priority) for one bank row.

    The priority comes along so it stays visible *why* something was labelled: a
    low priority means a hard, specific rule, a high one that it was caught by the
    personal name heuristic. 999 is 'nothing matched'.
    """
    name = (name or "").upper()
    counterparty = (counterparty_iban or "").upper()
    memo = f"{(description or '').upper()} {counterparty}".strip()

    # Money to an own account is never an expense. Before the rule table, because
    # this knowledge is harder than any pattern.
    if counterparty and own_ibans and counterparty in own_ibans:
        return OWN_ACCOUNT_CATEGORY, OWN_ACCOUNT_PRIORITY
    # Likewise when another own account is in the description. For a transfer to
    # your savings account ING puts no counterparty IBAN, but your own name ("Hr J
    # de Vries") and "To Oranje spaarrekening D12345678" — and that name turned it
    # into "paid to friends" through the person rule.
    if own_numbers and names_own_account(description, own_numbers):
        return OWN_ACCOUNT_CATEGORY, OWN_ACCOUNT_PRIORITY

    # Spending is positive, so a negative amount is incoming ('C').
    direction = "C" if amount < 0 else "D"

    found = _search(rules, name=name, memo=memo, direction=direction)
    if found:
        return found

    # Second round for payment processors: the real shop is in the description, so
    # that goes into the name rules here.
    if _PROCESSOR.search(name) and memo:
        found = _search(rules, name=memo[:200], memo="", direction=direction)
        if found and found[0] != UNKNOWN:
            # +100 so it stays visible afterwards that this was the second round.
            return found[0], found[1] + 100

    return UNKNOWN, 999


# The type of a transaction — EXPENSE, INCOME or INTERNAL — is no longer
# determined here. It follows from the category you see, and lives as a rule in
# the view bank_transactions_typed (database.init_db). Storing it here made it a
# cache that went stale as soon as you corrected a category by hand.


def unknown_per_counterparty(conn: sqlite3.Connection, *, limit: int = 30) -> list[dict]:
    """What has no category yet, per counterparty, the largest group first.

    Coverage rises fastest where many transactions share the same name: one rule
    for a counterparty that occurs two hundred times does more than ten rules for
    separate payments. Hence by count, and at equal count by amount. `total`
    follows the sign convention: spending positive.

    `processor`: the name is a payment processor (Mollie, Adyen, ...). Different
    shops sit behind it, so one rule on that name labels them all the same; the
    screen then advises labelling per transaction.
    """
    rows = conn.execute(
        """
        SELECT name,
               COUNT(*)          AS count,
               ROUND(CAST(SUM(amount) AS NUMERIC), 2) AS total,
               MAX(date)        AS last,
               MAX(description) AS example
          FROM bank_transactions_typed
         WHERE COALESCE(category_effective, 'Onbekend') = 'Onbekend'
           AND TRIM(COALESCE(name, '')) != ''
         GROUP BY name
         ORDER BY count DESC, ABS(SUM(amount)) DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{**dict(r), "processor": bool(_PROCESSOR.search((r["name"] or "").upper()))} for r in rows]


def unknown_count(conn: sqlite3.Connection) -> int:
    """How many transactions have no category yet: the counter at To label."""
    return conn.execute(
        "SELECT COUNT(*) FROM bank_transactions_typed WHERE COALESCE(category_effective, 'Onbekend') = 'Onbekend'"
    ).fetchone()[0]


# What makes a label suspicious, without knowing anything per person or bank.
_SUSPICIOUS_SAVES = (OWN_ACCOUNT_CATEGORY, "Naar spaarrekening", "Naar beleggen", "Creditcard aflossing")


def suspicious(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    """Transactions the rules probably labelled wrong, with the reason.

    Two signs that the money actually moved between your own accounts:

      * **your own account in the description** — an iDEAL top-up of bunq from
        your ING is called "Adyen Merchant Payout", with your ING IBAN in the
        description;
      * **the name of your own transfers** — the counterparty has exactly the
        name of a transfer that demonstrably came from an own account.

    Only what the rules labelled: what you set by hand is your judgement. The
    suggestion is Own accounts; the screen lets you choose.
    """
    ibans = {i for i in own_ibans(conn) if i}
    iban_of = {r["id"]: accounts.normalise_iban(r["iban"]) for r in conn.execute("SELECT id, iban FROM accounts")}
    own_names = {
        (r["name"] or "").strip().upper()
        for r in conn.execute("SELECT name, counterparty_iban FROM bank_transactions")
        if accounts.normalise_iban(r["counterparty_iban"]) in ibans and len((r["name"] or "").strip()) >= 3
    }
    places = ",".join("?" * len(_SUSPICIOUS_SAVES))
    off = []
    for r in conn.execute(
        f"""
        SELECT id, date, account_id, amount, name, description, counterparty_iban, category_effective
          FROM bank_transactions_typed
         WHERE category_manual IS NULL
           AND COALESCE(category_effective, '') NOT IN ({places})
        """,
        _SUSPICIOUS_SAVES,
    ):
        text = re.sub(r"\s+", "", (r["description"] or "").upper())
        other = ibans - {iban_of.get(r["account_id"])}
        if any(i in text for i in other):
            reason = tr("Your own account is in the description.")
        elif (r["name"] or "").strip().upper() in own_names:
            reason = tr("The same name as on your transfers between your own accounts.")
        else:
            continue
        off.append({**dict(r), "reason": reason, "suggestion": OWN_ACCOUNT_CATEGORY})
    return sorted(off, key=lambda v: -abs(v["amount"]))[:limit]


def relabel(conn: sqlite3.Connection, *, everything: bool = False) -> dict:
    """Relabels bank rows. Never touches `category_manual`.

    By default only what has no automatic category yet or stayed unknown; with
    `everything` the rest too, which is what you want after changing a rule.
    Unknown takes part because since the previous round something may have been
    added that does recognise it: a rule, or an account whose IBAN turns out to be
    the counterparty — savings transfers imported before the current account
    otherwise stayed an expense forever. Manual categories stay in place either
    way: they are not written here, and `category` reads manual before auto.
    """
    rules = load_rules(conn)
    ibans = own_ibans(conn)

    labelled = 0
    unknown = 0

    rows = bank_transactions.load(conn)
    against = reversals(conn, rows)
    numbers = own_numbers(conn)
    all_numbers = set().union(*numbers.values())
    learnt = learned(conn)
    from_claude = ai_suggestions(conn)

    for row in rows:
        # The numbers of your other accounts: that the own one is in the description
        # (an interest credit) says nothing.
        other = all_numbers - numbers.get(row["account_id"], set())
        again = (
            everything
            or row["category_auto"] in (None, UNKNOWN)
            # A counterparty that turned out to be an own account since the previous round.
            # A transfer from your other bunq account in the name "J. de Vries" was first
            # "received from friends" — income — and stayed that, even after you uploaded
            # that account, because it already had a category.
            or (row["counterparty_iban"] in ibans
                and row["category_auto"] != OWN_ACCOUNT_CATEGORY)
            # Or a transfer whose other side has become known since.
            or (row["id"] in against and row["category_auto"] != against[row["id"]])
            # Or one that names an account you added since.
            or (row["category_auto"] != OWN_ACCOUNT_CATEGORY
                and names_own_account(row["description"], other))
            # What was on friends by guess, or was learned or suggested: a new own label or
            # a disabled Claude can change it.
            or row["category_auto"] in FRIENDS
            or row.get("category_source") in ("learned", "ai")
        )
        if not again:
            continue

        category, priority = label(
            rules,
            name=row["name"],
            description=row["description"],
            counterparty_iban=row["counterparty_iban"],
            amount=row["amount"],
            own_ibans=ibans,
            own_numbers=other,
        )
        # A proven reversal weighs more than any name rule; only "own account" (an IBAN
        # of yourself) is just as hard and stays.
        if row["id"] in against and category != OWN_ACCOUNT_CATEGORY:
            category = against[row["id"]]
        source = "rule"
        # What the rules did not know, or only put on friends by the name: first what
        # you did yourself for this counterparty, then what Claude suggested.
        weak = category in FRIENDS and priority >= 80
        if row["id"] not in against and (category == UNKNOWN or weak):
            own = from_learned(learnt, name=row["name"], counterparty_iban=row["counterparty_iban"], weak=weak)
            suggestion = from_claude.get(row["id"])
            if own:
                category, source = own, "learned"
            # For a friend only when the description says what for: otherwise it guesses on a name.
            elif suggestion and suggestion not in FRIENDS and (not weak or has_target_text(row["name"], row["description"])):
                category, source = suggestion, "ai"
        bank_transactions.set_category_auto(conn, row["id"], category, source, commit=False)
        labelled += 1

    conn.commit()
    # Unknown and coverage over *all* transactions, not over what this round went
    # through. Without "everything" it mainly goes over the unknown ones, and then
    # after an import it reported "0.5% coverage" for a history that was eighty
    # percent labelled. A category you set yourself counts as labelled.
    total, unknown = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(COALESCE(category_manual, category_auto, ?) = ?), 0) "
        "FROM bank_transactions",
        (UNKNOWN, UNKNOWN),
    ).fetchone()
    coverage = ((total - unknown) / total * 100) if total else 0.0
    return {"labelled": labelled, "unknown": unknown, "coverage": round(coverage, 1)}
