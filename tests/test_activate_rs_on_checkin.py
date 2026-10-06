"""activate_rs_on_checkin: booking placeholder RS rows (na, 0) become real dues at check-in."""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.database.models import RentStatus
from src.services.rent_schedule import activate_rs_on_checkin


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _Session:
    """Returns the na rows the real query would select (status=na, period >= check-in month)."""
    def __init__(self, rows, checkin):
        self.rows = [r for r in rows if r.status == RentStatus.na and r.period_month >= checkin.replace(day=1)]
    async def execute(self, _stmt): return _Result(self.rows)


def _rs(period, due, status):
    return SimpleNamespace(period_month=period, rent_due=Decimal(due), status=status)


def test_placeholder_and_recomputed_rows_become_pending():
    t = SimpleNamespace(id=1, checkin_date=date(2026, 10, 1), agreed_rent=Decimal("10000"),
                        security_deposit=Decimal("10000"), booking_amount=Decimal("3000"))
    recomputed = _rs(date(2026, 10, 1), "17000", RentStatus.na)   # approve already set rent_due
    placeholder = _rs(date(2026, 11, 1), "0", RentStatus.na)      # untouched rollover seed
    paid = _rs(date(2026, 10, 1), "17000", RentStatus.paid)
    asyncio.run(activate_rs_on_checkin(_Session([recomputed, placeholder, paid], t.checkin_date), t))
    assert recomputed.status == RentStatus.pending and recomputed.rent_due == Decimal("17000")
    assert placeholder.status == RentStatus.pending and placeholder.rent_due == Decimal("10000")
    assert paid.status == RentStatus.paid


def test_first_month_placeholder_gets_first_month_formula():
    t = SimpleNamespace(id=1, checkin_date=date(2026, 10, 1), agreed_rent=Decimal("10000"),
                        security_deposit=Decimal("10000"), booking_amount=Decimal("3000"))
    row = _rs(date(2026, 10, 1), "0", RentStatus.na)
    asyncio.run(activate_rs_on_checkin(_Session([row], t.checkin_date), t))
    assert row.rent_due == Decimal("17000") and row.status == RentStatus.pending
