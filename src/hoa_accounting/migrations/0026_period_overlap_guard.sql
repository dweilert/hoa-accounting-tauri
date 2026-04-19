-- Prevent overlapping accounting periods within the same fiscal year.
-- SQLite CHECK constraints cannot span rows, so triggers enforce this.
-- Both INSERT and UPDATE are covered.

CREATE TRIGGER IF NOT EXISTS trg_period_no_overlap_insert
BEFORE INSERT ON accounting_periods
BEGIN
    SELECT RAISE(ABORT, 'Accounting period dates overlap an existing period in this fiscal year.')
    WHERE EXISTS (
        SELECT 1 FROM accounting_periods
        WHERE fiscal_year = NEW.fiscal_year
          AND start_date <= NEW.end_date
          AND end_date   >= NEW.start_date
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_period_no_overlap_update
BEFORE UPDATE ON accounting_periods
BEGIN
    SELECT RAISE(ABORT, 'Accounting period dates overlap an existing period in this fiscal year.')
    WHERE EXISTS (
        SELECT 1 FROM accounting_periods
        WHERE fiscal_year = NEW.fiscal_year
          AND id != NEW.id
          AND start_date <= NEW.end_date
          AND end_date   >= NEW.start_date
    );
END;
