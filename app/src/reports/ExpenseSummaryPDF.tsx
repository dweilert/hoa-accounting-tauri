/**
 * Expense Summary PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type ExpenseRow = {
  category_name: string;
  total: number;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { flex: 1 }]}>Category</Text>
      <Text style={[S.tableHeaderCell, { width: "25%", textAlign: "right" }]}>Total</Text>
    </View>
  );
}

export function ExpenseSummaryPDF({
  rows,
  hoaName,
  runDate,
  year,
}: {
  rows: ExpenseRow[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const total = rows.reduce((s, r) => s + r.total, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Expense Summary — ${year}`} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No expenses for {year}.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { flex: 1 }]}>{r.category_name}</Text>
            <Text style={[S.tableCell, { width: "25%", textAlign: "right", color: C.red700 }]}>
              {fmt(r.total)}
            </Text>
          </View>
        ))}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: "25%", textAlign: "right", color: C.red700 }]}>
              {fmt(total)}
            </Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
