ALTER TABLE bank_transaction_rules ADD COLUMN category_id INTEGER REFERENCES categories(id);
