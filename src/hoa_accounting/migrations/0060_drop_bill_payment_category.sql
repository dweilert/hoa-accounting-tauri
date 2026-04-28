-- Migration 0060: Drop bill_payments.category_id (single source of truth).
--
-- Bill payments now inherit their category from the parent vendor_bill via
-- JOIN. Carrying an independent category on the payment row caused rule-engine
-- imports to mis-categorize payments while their bills were correctly tagged.
-- The bill's category is the only source of truth going forward.
--
-- Backfill any payments whose old category disagreed with the bill's, then
-- drop the column.

UPDATE bill_payments
   SET category_id = (
        SELECT vb.category_id FROM vendor_bills vb WHERE vb.id = bill_payments.vendor_bill_id
   )
 WHERE category_id IS NULL
    OR category_id <> (
        SELECT vb.category_id FROM vendor_bills vb WHERE vb.id = bill_payments.vendor_bill_id
   );

ALTER TABLE bill_payments DROP COLUMN category_id;
