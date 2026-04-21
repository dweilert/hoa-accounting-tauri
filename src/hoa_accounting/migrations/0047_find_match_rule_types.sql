-- Migration 0047: Storage for homeowner_batch and vendor_bill_match rule types
-- matched_payment_ids: JSON array of payment.id values matched to a batch deposit
-- matched_bill_ids:    JSON array of vendor_bill.id values matched to a debit
ALTER TABLE bank_transactions ADD COLUMN matched_payment_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE bank_transactions ADD COLUMN matched_bill_ids    TEXT NOT NULL DEFAULT '[]';
