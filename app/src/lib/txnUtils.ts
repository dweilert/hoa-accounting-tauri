export const SOURCE_LABELS: Record<string, string> = {
  PAYMENT:      "Payment",
  BILL_PAYMENT: "Expense Payment",
  INCOME:       "Income",
  ASSESSMENT:   "Owner Bill",
};

export type TxnLabelRow = { source_type: string; category: string | null };

export function rowLabel(r: TxnLabelRow): string {
  if (r.source_type === "ASSESSMENT") {
    if (r.category === "DUES") return "Bill Dues";
    if (r.category === "LATE_FEE" || r.category === "LEGAL_FEE") return "Bill Special";
    return "Bill Other";
  }
  return SOURCE_LABELS[r.source_type] ?? r.source_type;
}

export function fmtCurrency(n: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(n);
}
