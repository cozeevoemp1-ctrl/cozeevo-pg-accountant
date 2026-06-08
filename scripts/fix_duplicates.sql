-- Find and cancel duplicate active tenancies (keep earliest by checkin_date)
-- This identifies all (tenant_id, room_id) pairs with multiple active tenancies

WITH duplicates AS (
    SELECT tenant_id, room_id, COUNT(*) as cnt
    FROM tenancies
    WHERE status = 'active'
    GROUP BY tenant_id, room_id
    HAVING COUNT(*) > 1
),
ranked AS (
    SELECT
        t.id,
        t.tenant_id,
        t.room_id,
        t.checkin_date,
        t.created_at,
        ROW_NUMBER() OVER (PARTITION BY t.tenant_id, t.room_id ORDER BY t.checkin_date ASC, t.created_at ASC) as rn
    FROM tenancies t
    WHERE EXISTS (SELECT 1 FROM duplicates d WHERE d.tenant_id = t.tenant_id AND d.room_id = t.room_id)
    AND t.status = 'active'
)
SELECT id, tenant_id, room_id, checkin_date, created_at, rn
FROM ranked
ORDER BY tenant_id, room_id, rn;

-- To actually cancel the duplicates (keep rn=1, cancel rn>1):
--
-- UPDATE tenancies
-- SET status = 'cancelled'
-- WHERE id IN (
--     SELECT id FROM ranked WHERE rn > 1
-- )
-- AND status = 'active';
--
-- INSERT INTO audit_log (changed_by, entity_type, entity_id, entity_name, field, old_value, new_value, source, org_id, created_at)
-- SELECT
--     'fix_duplicates.sql',
--     'tenancy',
--     t.id,
--     'Tenant ' || t.tenant_id || ', Room ' || r.room_number,
--     'status',
--     'active',
--     'cancelled',
--     'script',
--     t.org_id,
--     NOW()
-- FROM tenancies t
-- JOIN rooms r ON r.id = t.room_id
-- WHERE t.id IN (SELECT id FROM ranked WHERE rn > 1);
