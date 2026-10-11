UPDATE tenancies SET status='active', checkin_date='2026-07-01', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=1;
UPDATE tenancies SET status='active', checkin_date='2026-04-19', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=3;
UPDATE tenancies SET status='active', checkin_date='2026-06-30', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=43;
UPDATE tenancies SET status='active', checkin_date='2026-06-17', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=101;
UPDATE tenancies SET status='active', checkin_date='2026-07-17', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=103;
UPDATE tenancies SET status='active', checkin_date='2026-04-21', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=110;
UPDATE tenancies SET status='active', checkin_date='2026-07-01', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=131;
UPDATE tenancies SET status='active', checkin_date='2026-06-04', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=151;
UPDATE tenancies SET status='active', checkin_date='2026-07-20', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=180;
UPDATE tenancies SET status='active', checkin_date='2026-03-19', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=187;
UPDATE tenancies SET status='active', checkin_date='2026-05-25', checkout_date=NULL, expected_checkout='2026-08-31', notice_date='2026-07-06' WHERE id=37;
UPDATE tenancies SET status='active', checkin_date='2026-06-08', checkout_date=NULL, expected_checkout='2026-07-31', notice_date='2026-07-01' WHERE id=129;
UPDATE tenancies SET status='active', checkin_date='2026-07-18', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE id=269;
DELETE FROM refunds WHERE tenancy_id IN (1,3,37,43,101,103,110,129,131,151,180,187,269) AND created_at > '2026-10-11 12:20';
DELETE FROM checkout_records WHERE tenancy_id IN (1,3,37,43,101,103,110,129,131,151,180,187,269) AND created_at > '2026-10-11 12:20';
UPDATE onboarding_sessions SET status='cancelled' WHERE tenant_phone ~ '98765000(1[01]|0[0-9])$' AND status IN ('pending_tenant','pending_review');
-- Lifecycle fixtures (rooms 213, 221 only). Idempotent: resets fixture state.
INSERT INTO tenants (name, phone) SELECT 'Arnav Kulkarni','9000009001' WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE phone='9000009001');
INSERT INTO tenants (name, phone) SELECT 'Bhoomi Iyer','9000009002' WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE phone='9000009002');
INSERT INTO tenancies (tenant_id, room_id, stay_type, sharing_type, status, checkin_date, booking_amount, security_deposit, maintenance_fee, agreed_rent, entered_by, created_at, updated_at)
  SELECT t.id, (SELECT id FROM rooms WHERE room_number='213'), 'monthly','single','no_show','2026-10-09',5000,15000,0,15000,'lifecycle_fixture',now(),now()
  FROM tenants t WHERE t.phone='9000009001' AND NOT EXISTS (SELECT 1 FROM tenancies x WHERE x.tenant_id=t.id);
INSERT INTO tenancies (tenant_id, room_id, stay_type, sharing_type, status, checkin_date, booking_amount, security_deposit, maintenance_fee, agreed_rent, entered_by, created_at, updated_at)
  SELECT t.id, (SELECT id FROM rooms WHERE room_number='221'), 'monthly','double','no_show','2026-10-10',0,12000,0,12000,'lifecycle_fixture',now(),now()
  FROM tenants t WHERE t.phone='9000009002' AND NOT EXISTS (SELECT 1 FROM tenancies x WHERE x.tenant_id=t.id);
UPDATE tenancies SET status='no_show', checkin_date=CASE WHEN tenant_id=(SELECT id FROM tenants WHERE phone='9000009001') THEN DATE '2026-10-09' ELSE DATE '2026-10-10' END
  WHERE tenant_id IN (SELECT id FROM tenants WHERE phone IN ('9000009001','9000009002'));
UPDATE payments SET is_void=true WHERE tenancy_id IN (SELECT x.id FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone IN ('9000009001','9000009002')) AND notes LIKE 'Collected at check-in%';
DELETE FROM rent_schedule WHERE tenancy_id IN (SELECT x.id FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone IN ('9000009001','9000009002'));
INSERT INTO rent_schedule (tenancy_id, period_month, rent_due, maintenance_due, status, due_date)
  SELECT x.id, DATE '2026-10-01', 0, 0, 'na', DATE '2026-10-01' FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone IN ('9000009001','9000009002');
SELECT x.id, t.name, x.status, x.checkin_date FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone IN ('9000009001','9000009002');
-- Checkout fixtures (unique first names so a repeat run finds nobody instead of a namesake)
INSERT INTO tenants (name, phone) SELECT v.n, v.p FROM (VALUES ('Zorawar Bedi','9000009011'),('Quincy Dsouza','9000009012'),('Ujjwal Rana','9000009013'),('Xerxes Irani','9000009014'),('Yohan Tamboli','9000009015')) v(n,p) WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE phone=v.p);
INSERT INTO tenancies (tenant_id, room_id, stay_type, sharing_type, status, checkin_date, booking_amount, security_deposit, maintenance_fee, agreed_rent, entered_by, created_at, updated_at)
  SELECT t.id, (SELECT id FROM rooms WHERE room_number=v.r), v.st::staytype, 'double', 'active', v.ci::date, 0, v.dep, 0, v.rent, 'lifecycle_fixture', now(), now()
  FROM (VALUES ('9000009011','106','monthly','2026-06-01',14000,14000),('9000009012','117','monthly','2026-06-01',13000,13000),('9000009013','118','daily','2026-10-08',2000,800),('9000009014','105','monthly','2026-06-01',12000,12000),('9000009015','110','monthly','2026-06-01',12500,12500)) v(p,r,st,ci,dep,rent)
  JOIN tenants t ON t.phone=v.p WHERE NOT EXISTS (SELECT 1 FROM tenancies x WHERE x.tenant_id=t.id);
UPDATE tenancies SET status='active', checkout_date=NULL, expected_checkout=NULL, notice_date=NULL WHERE tenant_id IN (SELECT id FROM tenants WHERE phone BETWEEN '9000009011' AND '9000009015');
DELETE FROM checkout_records WHERE tenancy_id IN (SELECT x.id FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone BETWEEN '9000009011' AND '9000009015');
DELETE FROM refunds WHERE tenancy_id IN (SELECT x.id FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone BETWEEN '9000009011' AND '9000009015');
DELETE FROM audit_log WHERE entity_type='tenancy' AND entity_id IN (SELECT x.id FROM tenancies x JOIN tenants t ON t.id=x.tenant_id WHERE t.phone BETWEEN '9000009001' AND '9000009015');
DELETE FROM audit_log WHERE entity_type='tenancy' AND entity_id IN (3,37,101,103,110,129,131,187) AND source='whatsapp';
SELECT x.id, t.name, r.room_number, x.status, x.stay_type FROM tenancies x JOIN tenants t ON t.id=x.tenant_id JOIN rooms r ON r.id=x.room_id WHERE t.phone LIKE '900000901%' OR t.phone LIKE '900000900%' ORDER BY x.id;
