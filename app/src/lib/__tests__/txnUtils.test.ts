import { describe, it, expect } from "vitest";
import { SOURCE_LABELS, rowLabel, fmtCurrency } from "../txnUtils";

describe("SOURCE_LABELS", () => {
  it("maps PAYMENT", () => expect(SOURCE_LABELS["PAYMENT"]).toBe("Payment"));
  it("maps BILL_PAYMENT", () => expect(SOURCE_LABELS["BILL_PAYMENT"]).toBe("Expense Payment"));
  it("maps INCOME", () => expect(SOURCE_LABELS["INCOME"]).toBe("Income"));
  it("maps ASSESSMENT", () => expect(SOURCE_LABELS["ASSESSMENT"]).toBe("Owner Bill"));
});

describe("rowLabel", () => {
  it("ASSESSMENT + DUES returns 'Bill Dues'", () => {
    expect(rowLabel({ source_type: "ASSESSMENT", category: "DUES" })).toBe("Bill Dues");
  });

  it("ASSESSMENT + LATE_FEE returns 'Bill Special'", () => {
    expect(rowLabel({ source_type: "ASSESSMENT", category: "LATE_FEE" })).toBe("Bill Special");
  });

  it("ASSESSMENT + LEGAL_FEE returns 'Bill Special'", () => {
    expect(rowLabel({ source_type: "ASSESSMENT", category: "LEGAL_FEE" })).toBe("Bill Special");
  });

  it("ASSESSMENT + OTHER returns 'Bill Other'", () => {
    expect(rowLabel({ source_type: "ASSESSMENT", category: "RESALE_FEE" })).toBe("Bill Other");
  });

  it("ASSESSMENT + null category returns 'Bill Other'", () => {
    expect(rowLabel({ source_type: "ASSESSMENT", category: null })).toBe("Bill Other");
  });

  it("PAYMENT returns 'Payment'", () => {
    expect(rowLabel({ source_type: "PAYMENT", category: null })).toBe("Payment");
  });

  it("BILL_PAYMENT returns 'Expense Payment'", () => {
    expect(rowLabel({ source_type: "BILL_PAYMENT", category: null })).toBe("Expense Payment");
  });

  it("INCOME returns 'Income'", () => {
    expect(rowLabel({ source_type: "INCOME", category: "OTHER_INCOME" })).toBe("Income");
  });

  it("unknown source_type falls back to source_type itself", () => {
    expect(rowLabel({ source_type: "MYSTERY_TYPE", category: null })).toBe("MYSTERY_TYPE");
  });
});

describe("fmtCurrency", () => {
  it("formats positive USD", () => {
    expect(fmtCurrency(1234.56)).toBe("$1,234.56");
  });

  it("formats zero", () => {
    expect(fmtCurrency(0)).toBe("$0.00");
  });

  it("formats negative value", () => {
    expect(fmtCurrency(-500)).toBe("-$500.00");
  });

  it("accepts alternate currency", () => {
    const result = fmtCurrency(100, "EUR");
    expect(result).toContain("100");
  });

  it("rounds to two decimal places", () => {
    expect(fmtCurrency(9.999)).toBe("$10.00");
  });
});
