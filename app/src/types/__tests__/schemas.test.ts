import { describe, it, expect } from "vitest";
import { PaymentFormSchema, DepositBatchSchema, PaymentMethodType, PaymentType } from "../deposit";
import { LotFormSchema } from "../lot";
import { VendorFormSchema } from "../vendor";

// ── PaymentFormSchema ─────────────────────────────────────────────────────────

describe("PaymentFormSchema", () => {
  const valid = {
    lot_id: 1,
    payment_date: "2024-03-01",
    amount: 250,
    payment_method: "CHECK",
    payment_type: "DUES",
    notes: null,
  };

  it("accepts valid payment", () => {
    expect(() => PaymentFormSchema.parse(valid)).not.toThrow();
  });

  it("rejects missing lot_id", () => {
    const { lot_id, ...rest } = valid;
    expect(() => PaymentFormSchema.parse(rest)).toThrow();
  });

  it("rejects negative amount", () => {
    expect(() => PaymentFormSchema.parse({ ...valid, amount: -1 })).toThrow();
  });

  it("rejects zero amount", () => {
    expect(() => PaymentFormSchema.parse({ ...valid, amount: 0 })).toThrow();
  });

  it("rejects invalid payment_method", () => {
    expect(() => PaymentFormSchema.parse({ ...valid, payment_method: "WIRE" })).toThrow();
  });

  it("rejects invalid payment_type", () => {
    expect(() => PaymentFormSchema.parse({ ...valid, payment_type: "GIFT" })).toThrow();
  });

  it("accepts null notes", () => {
    expect(() => PaymentFormSchema.parse({ ...valid, notes: null })).not.toThrow();
  });
});

// ── PaymentMethodType ─────────────────────────────────────────────────────────

describe("PaymentMethodType", () => {
  const valid = ["CHECK", "ACH", "ONLINE", "CASH", "OTHER"];
  it.each(valid)("accepts %s", (m) => {
    expect(() => PaymentMethodType.parse(m)).not.toThrow();
  });
  it("rejects WIRE", () => {
    expect(() => PaymentMethodType.parse("WIRE")).toThrow();
  });
});

// ── PaymentType ───────────────────────────────────────────────────────────────

describe("PaymentType", () => {
  it("accepts DUES", () => {
    expect(() => PaymentType.parse("DUES")).not.toThrow();
  });
  it("rejects GIFT", () => {
    expect(() => PaymentType.parse("GIFT")).toThrow();
  });
});

// ── DepositBatchSchema ────────────────────────────────────────────────────────

describe("DepositBatchSchema", () => {
  const valid = {
    id: 1,
    deposit_date: "2024-03-01",
    bank_account_id: 2,
    status: "OPEN",
    notes: null,
    total_amount: 0,
    check_count: 0,
    created_at: "2024-03-01T00:00:00",
    updated_at: "2024-03-01T00:00:00",
  };

  it("accepts valid batch", () => {
    expect(() => DepositBatchSchema.parse(valid)).not.toThrow();
  });

  it("rejects invalid status", () => {
    expect(() => DepositBatchSchema.parse({ ...valid, status: "DRAFT" })).toThrow();
  });

  it("accepts POSTED status", () => {
    expect(() => DepositBatchSchema.parse({ ...valid, status: "POSTED" })).not.toThrow();
  });
});

// ── LotFormSchema ─────────────────────────────────────────────────────────────

describe("LotFormSchema", () => {
  const valid = {
    lot_number: "101",
    active_flag: 1,
  };

  it("accepts minimal lot (lot_number + active_flag only)", () => {
    expect(() => LotFormSchema.parse(valid)).not.toThrow();
  });

  it("rejects empty lot_number", () => {
    expect(() => LotFormSchema.parse({ ...valid, lot_number: "" })).toThrow();
  });

  it("rejects missing lot_number", () => {
    const { lot_number, ...rest } = valid;
    expect(() => LotFormSchema.parse(rest)).toThrow();
  });

  it("accepts full address fields", () => {
    expect(() => LotFormSchema.parse({
      ...valid,
      street_address_1: "123 Main",
      city: "Austin",
      state: "TX",
      postal_code: "78701",
    })).not.toThrow();
  });

  it("rejects state longer than 2 chars", () => {
    expect(() => LotFormSchema.parse({ ...valid, state: "TEX" })).toThrow();
  });
});

// ── VendorFormSchema ──────────────────────────────────────────────────────────

describe("VendorFormSchema", () => {
  const valid = {
    vendor_name: "ACME Landscaping",
    active_flag: 1,
  };

  it("accepts minimal vendor", () => {
    expect(() => VendorFormSchema.parse(valid)).not.toThrow();
  });

  it("rejects empty vendor_name", () => {
    expect(() => VendorFormSchema.parse({ ...valid, vendor_name: "" })).toThrow();
  });

  it("rejects invalid email format", () => {
    expect(() => VendorFormSchema.parse({ ...valid, email: "not-an-email" })).toThrow();
  });

  it("accepts valid email", () => {
    expect(() => VendorFormSchema.parse({ ...valid, email: "vendor@example.com" })).not.toThrow();
  });

  it("accepts empty string email (optional cleared field)", () => {
    expect(() => VendorFormSchema.parse({ ...valid, email: "" })).not.toThrow();
  });
});
