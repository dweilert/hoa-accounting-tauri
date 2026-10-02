/**
 * Expense Detail PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type ExpenseDetailRow = {
  payment_date: string;
  vendor_name: string;
  invoice_number: string;
  category_name: string;
  amount: number;
  check_number: string | null;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Column widths — must sum to 100% and Amount width must match total row
const W = { date: "12%", vendor: "28%", invoice: "15%", category: "30%", amount: "15%" };

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { width: W.date }]}>Date</Text>
      <Text style={[S.tableHeaderCell, { width: W.vendor }]}>Vendor</Text>
      <Text style={[S.tableHeaderCell, { width: W.invoice }]}>Invoice</Text>
      <Text style={[S.tableHeaderCell, { width: W.category }]}>Category</Text>
      <Text style={[S.tableHeaderCell, { width: W.amount, textAlign: "right" }]}>Amount</Text>
    </View>
  );
}

export function ExpenseDetailPDF({
  rows,
  hoaName,
  runDate,
  year,
}: {
  rows: ExpenseDetailRow[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const total = rows.reduce((s, r) => s + r.amount, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Expense Detail — ${year}`} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No expense payments for {year}.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell,      { width: W.date }]}>{r.payment_date}</Text>
            <Text style={[S.tableCell,      { width: W.vendor }]}>{r.vendor_name}</Text>
            <Text style={[S.tableCellMuted, { width: W.invoice }]}>{r.invoice_number}</Text>
            <Text style={[S.tableCellMuted, { width: W.category }]}>{r.category_name ?? "—"}</Text>
            <Text style={[S.tableCellMono,  { width: W.amount, textAlign: "right", color: C.red700 }]}>
              {fmt(r.amount)}
            </Text>
          </View>
        ))}

        {/* Total row — Amount column width matches header exactly so numbers align */}
        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: W.amount, textAlign: "right", color: C.red700, fontFamily: "Courier" }]}>
              {fmt(total)}
            </Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
