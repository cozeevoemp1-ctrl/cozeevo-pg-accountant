"""floor_of() + BedBreakdown.subset(building, floor) — the vacancy floor filter."""
from datetime import date

from src.services.occupancy import BedBreakdown, RoomBeds, floor_of


def _rb(rid, rn, building, free=1):
    return RoomBeds(rid, rn, building, 2, 2 - free, 0, 0, free, 0, 0)


BB = BedBreakdown(date(2026, 10, 11), {
    1: _rb(1, "G03", "Cozeevo THOR"),
    2: _rb(2, "314", "Cozeevo HULK"),
    3: _rb(3, "317", "Cozeevo HULK", free=0),
    4: _rb(4, "308", "Cozeevo THOR"),
    5: _rb(5, "223", "Cozeevo HULK"),
})


def test_floor_of():
    assert floor_of("G03") == "G"
    assert floor_of("g17") == "G"
    assert floor_of("314") == "3"
    assert floor_of("") == ""


def test_subset_no_filter_is_identity():
    assert BB.subset() is BB


def test_subset_floor_only():
    assert sorted(r.room_number for r in BB.subset(floor="3").rooms.values()) == ["308", "314", "317"]
    assert BB.subset(floor="3").vacant == 2


def test_subset_building_and_floor():
    assert [r.room_number for r in BB.subset("HULK", "2").rooms.values()] == ["223"]
    assert [r.room_number for r in BB.subset("THOR", "G").rooms.values()] == ["G03"]
    assert BB.subset("THOR", "2").rooms == {}
