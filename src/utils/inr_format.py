"""Indian number formatting utilities — lakh/crore grouping.

Single source of truth for rupee formatting across the project.
Use INR_NUMBER_FORMAT for openpyxl cells; use inr() / inr_short() for Python strings.

Grouping example:
    10740175 -> "1,07,40,175"
    152832000 -> "15,28,32,000"

Short form (with unit):
    152832000 -> "Rs.15.28 Cr"
    1740175   -> "Rs.17.40 L"
    8500      -> "Rs.8,500"
"""

# openpyxl number_format — Indian lakh/crore grouping with ₹ symbol.
# Sections: >99,99,999 (crore) | >99,999 (lakh) | otherwise
INR_NUMBER_FORMAT = '[>9999999][$₹]##\\,##\\,##\\,##0;[>99999][$₹]##\\,##\\,##0;[$₹]##,##0'
INR_NUMBER_FORMAT_2DP = '[>9999999][$₹]##\\,##\\,##\\,##0.00;[>99999][$₹]##\\,##\\,##0.00;[$₹]##,##0.00'


def inr(n, zero_dash: bool = True) -> str:
    """Format an integer in Indian comma grouping: 10740175 -> '1,07,40,175'."""
    if n is None:
        return "-" if zero_dash else "0"
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return str(n)
    if n == 0:
        return "-" if zero_dash else "0"
    neg = n < 0
    s = str(abs(n))
    if len(s) <= 3:
        body = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        body = ",".join(groups) + "," + last3
    return f"({body})" if neg else body


def inr_short(n, prefix: str = "Rs.") -> str:
    """Compact lakh/crore form: 152832000 -> 'Rs.15.28 Cr', 1740175 -> 'Rs.17.40 L'."""
    if n is None or n == 0:
        return f"{prefix}0"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    neg = n < 0
    v = abs(n)
    if v >= 10_000_000:
        body = f"{v / 10_000_000:.2f} Cr"
    elif v >= 100_000:
        body = f"{v / 100_000:.2f} L"
    else:
        body = inr(v, zero_dash=False)
    return f"{prefix}{'-' if neg else ''}{body}"
