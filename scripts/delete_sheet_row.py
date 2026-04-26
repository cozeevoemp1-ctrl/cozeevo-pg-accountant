"""
One-off script: delete Prasanth P (room G09) rows from Google Sheet.
Removes from TENANTS master tab + April 2026 monthly tab.
Safe to re-run — will report "not found" if already deleted.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.integrations.gsheets import (
    _get_worksheet_sync,
    _find_row_in_tenants,
    _find_row_in_monthly,
)

DELETIONS = [
    {"room": "114", "name": "Arun R L",  "month": "APRIL 2026"},
    {"room": "114", "name": "Pooja K L", "month": "APRIL 2026"},
]


def delete_row(ws, row_idx: int, label: str):
    ws.delete_rows(row_idx)
    print(f"  DELETED row {row_idx} from {label}")


def main():
    ws_t = _get_worksheet_sync("TENANTS")

    for d in DELETIONS:
        room, name, month = d["room"], d["name"], d["month"]
        print(f"Deleting '{name}' / room {room}…")

        # TENANTS tab
        try:
            result = _find_row_in_tenants(ws_t, room, name)
            if result:
                row_idx, row_data = result
                print(f"  Found in TENANTS at row {row_idx}: {row_data[:5]}")
                delete_row(ws_t, row_idx, "TENANTS")
                # Re-fetch after delete so row numbers stay accurate
                ws_t = _get_worksheet_sync("TENANTS")
            else:
                print(f"  Not found in TENANTS")
        except Exception as e:
            print(f"  ERROR in TENANTS: {e}")

        # Monthly tab
        try:
            ws_m = _get_worksheet_sync(month)
            result = _find_row_in_monthly(ws_m, room, name)
            if result:
                row_idx, row_data = result
                print(f"  Found in '{month}' at row {row_idx}: {row_data[:5]}")
                delete_row(ws_m, row_idx, month)
            else:
                print(f"  Not found in '{month}'")
        except Exception as e:
            print(f"  ERROR in '{month}': {e}")

    print("Done.")


if __name__ == "__main__":
    main()
