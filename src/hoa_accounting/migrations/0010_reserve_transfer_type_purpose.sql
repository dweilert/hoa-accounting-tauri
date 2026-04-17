-- Migration 0010: Add transfer_type and purpose to reserve_transfers
--
-- transfer_type: FUND (Operating → Reserve) or WITHDRAW (Reserve → Operating)
-- purpose: required for WITHDRAW, records what reserve item is being funded.
--          Both columns are nullable here; validation is enforced in the page layer.

BEGIN TRANSACTION;

ALTER TABLE reserve_transfers
    ADD COLUMN transfer_type TEXT
        CHECK (transfer_type IN ('FUND', 'WITHDRAW'));

ALTER TABLE reserve_transfers
    ADD COLUMN purpose TEXT;

COMMIT;
