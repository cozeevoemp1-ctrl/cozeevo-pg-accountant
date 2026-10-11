"""Canonical occupancy calculations — single source of truth for all endpoints."""
from dataclasses import dataclass, field
from datetime import date
from sqlalchemy import case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Room, Tenancy, TenancyStatus


def revenue_room_filter() -> tuple:
    """WHERE clauses for revenue rooms — the one definition of "a sellable bed"
    (staff rooms and placeholder room 000 excluded). Use it, never re-type it."""
    return (Room.is_staff_room == False, Room.room_number != "000")


@dataclass
class RoomBeds:
    room_id: int
    room_number: str
    building: str
    max_beds: int
    checked_in: int     # active tenancies (incl. day-stays), capped at max_beds
    daystay: int        # part of checked_in that is day-stay
    noshow: int         # beds held by no-shows whose check-in date has arrived
    free: int           # max_beds - checked_in - noshow (never negative)
    over: int           # bookings that did not fit (double-booked room = data error)
    upcoming: int       # no-shows arriving after the target date (bed free until then)


@dataclass
class BedBreakdown:
    target_date: date
    rooms: dict = field(default_factory=dict)   # room_id -> RoomBeds

    def subset(self, building: str | None = None) -> "BedBreakdown":
        """Same breakdown restricted to one building (substring, case-insensitive)."""
        if not building:
            return self
        b = building.upper()
        return BedBreakdown(self.target_date,
                            {k: v for k, v in self.rooms.items() if b in v.building.upper()})

    def _sum(self, attr: str) -> int:
        return sum(getattr(r, attr) for r in self.rooms.values())

    @property
    def total_beds(self) -> int: return self._sum("max_beds")
    @property
    def checked_in(self) -> int: return self._sum("checked_in")
    @property
    def daystay(self) -> int: return self._sum("daystay")
    @property
    def noshow(self) -> int: return self._sum("noshow")
    @property
    def vacant(self) -> int: return self._sum("free")
    @property
    def over(self) -> int: return self._sum("over")
    @property
    def upcoming(self) -> int: return self._sum("upcoming")
    @property
    def over_rooms(self) -> list: return sorted(r.room_number for r in self.rooms.values() if r.over)


async def get_total_revenue_beds(session: AsyncSession) -> int:
    """Total revenue beds (exclude staff rooms and placeholder room 000)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Room.max_occupancy), 0))
        .where(*revenue_room_filter())
    )
    return int(total or 0)


def get_total_revenue_beds_sync() -> int:
    """Sync variant for thread-run code (gsheets summary refresh) with no
    async session. Opens its own short-lived engine from DATABASE_URL.
    Returns 0 if the DB is unreachable — callers must fall back explicitly."""
    import os
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if not url:
        return 0
    try:
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                total = conn.scalar(
                    select(func.coalesce(func.sum(Room.max_occupancy), 0))
                    .where(*revenue_room_filter())
                )
        finally:
            engine.dispose()
        return int(total or 0)
    except Exception:
        return 0


async def get_bed_breakdown(session: AsyncSession, target_date: date | None = None) -> BedBreakdown:
    """THE bed-state calculation. Every surface that shows occupied / no-show /
    vacant beds (bot: vacant rooms, occupancy, day-stay tonight, master data;
    PWA: KPI tile via get_occupied_beds) must derive from this.

    Per revenue room (canonical filter: not staff, not room 000):
      active   = active tenancies (monthly + day-stay); premium = max_occupancy
      held     = no-shows whose checkin_date <= target_date (bed reserved)
      upcoming = no-shows arriving after target_date (bed still free tonight)
    Today: active = status only (here until checked out). Future target_date:
    stays with checkout_date <= target_date are treated as gone.
    Each room is capped at max_occupancy, active first:
      checked_in = min(active, max);  noshow = min(held, max - checked_in)
      free = max - checked_in - noshow;  over = what did not fit (data error)
    so checked_in + noshow + vacant == total_beds always holds.
    """
    from src.database.models import Property, StayType

    target_date = target_date or date.today()
    out = BedBreakdown(target_date=target_date)

    room_rows = (await session.execute(
        select(Room.id, Room.room_number, Room.max_occupancy, Property.name)
        .join(Property, Property.id == Room.property_id, isouter=True)
        .where(*revenue_room_filter())
    )).all()
    raw: dict[int, dict] = {}
    for rid, rn, max_occ, prop in room_rows:
        raw[rid] = {"room_number": rn, "max": int(max_occ or 0), "building": prop or "",
                    "active": 0, "daystay": 0, "held": 0, "upcoming": 0}

    t_rows = (await session.execute(
        select(Tenancy.room_id, Tenancy.status, Tenancy.sharing_type,
               Tenancy.stay_type, Tenancy.checkin_date, Tenancy.checkout_date)
        .where(Tenancy.room_id.in_(list(raw.keys()) or [-1]),
               Tenancy.status.in_([TenancyStatus.active, TenancyStatus.no_show]))
    )).all()
    future = target_date > date.today()
    for rid, status, sharing, stay, checkin, checkout in t_rows:
        r = raw[rid]
        # Future date: a stay whose checkout_date falls on/before it has left.
        if future and checkout is not None and checkout <= target_date:
            continue
        if future and status == TenancyStatus.active and checkin and checkin > target_date:
            continue
        sh = sharing.value if hasattr(sharing, "value") else sharing
        beds = r["max"] if sh == "premium" else 1
        if status == TenancyStatus.active:
            r["active"] += beds
            if stay == StayType.daily:
                r["daystay"] += beds
        elif checkin is None or checkin <= target_date:
            r["held"] += beds
        else:
            r["upcoming"] += 1

    for rid, r in raw.items():
        mx = r["max"]
        ci = min(r["active"], mx)
        ns = min(r["held"], mx - ci)
        rb = RoomBeds(
            room_id=rid, room_number=r["room_number"], building=r["building"],
            max_beds=mx, checked_in=ci, daystay=min(r["daystay"], ci), noshow=ns,
            free=mx - ci - ns, over=r["active"] + r["held"] - ci - ns,
            upcoming=r["upcoming"],
        )
        out.rooms[rid] = rb
    return out


async def get_occupied_beds(session: AsyncSession, target_date: date) -> int:
    """Occupied beds on target_date: checked-in + held no-shows, per-room capped.
    Derived from get_bed_breakdown() so the PWA tile, the PWA vacant-room list
    and the bot all agree (a no-show in an already-full room no longer eats a
    bed that doesn't exist)."""
    b = await get_bed_breakdown(session, target_date)
    return b.checked_in + b.noshow


async def get_occupied_beds_asof(session: AsyncSession, target_date: date) -> int:
    """Point-in-time occupied beds on target_date — for HISTORICAL months.

    Reconstructs occupancy as it actually was on target_date by counting everyone
    PRESENT then (checkin <= target and not yet checked out), INCLUDING tenancies
    that have since exited. `get_occupied_beds` filters by current 'active' status
    with no date bound, so it always returns *today's* count — wrong for past
    months (it makes every recent month show the same number). Use THIS for any
    date other than today. Per-room sum capped at max_occupancy; premium = full room.
    """
    per_room = (
        select(
            func.least(
                func.sum(
                    case(
                        (Tenancy.sharing_type == "premium", Room.max_occupancy),
                        else_=literal_column("1"),
                    )
                ),
                Room.max_occupancy,
            ).label("capped")
        )
        .select_from(Tenancy)
        .join(Room, Room.id == Tenancy.room_id)
        .where(
            *revenue_room_filter(),
            Tenancy.status.in_([
                TenancyStatus.active, TenancyStatus.exited, TenancyStatus.no_show,
            ]),
            Tenancy.checkin_date.isnot(None),
            Tenancy.checkin_date <= target_date,
            or_(Tenancy.checkout_date.is_(None), Tenancy.checkout_date >= target_date),
        )
        .group_by(Room.id, Room.max_occupancy)
        .subquery()
    )
    return int(await session.scalar(select(func.coalesce(func.sum(per_room.c.capped), 0))) or 0)


async def get_occupancy_pct(session: AsyncSession, target_date: date) -> float:
    """Occupancy percentage on target_date (0-100)."""
    total_beds = await get_total_revenue_beds(session)
    occupied = await get_occupied_beds(session, target_date)
    if total_beds == 0:
        return 0.0
    return round(occupied / total_beds * 100, 1)
