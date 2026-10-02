/**
 * Delinquency Report PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type DelinquencyRow = {
  lot_number: string;
  owner_name: string | null;
  email: string | null;
  phone: string | null;
  open_amount: number;
  oldest_due_date: string | null;
  days_overdue: number;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function daysOverdueColor(days: number): string {
  if (days > 90) return C.red700;
  if (days > 30) return "#ea580c";
  return "#ca8a04";
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { width: "10%" }]}>Lot</Text>
      <Text style={[S.tableHeaderCell, { width: "25%" }]}>Owner</Text>
      <Text style={[S.tableHeaderCell, { width: "25%" }]}>Contact</Text>
      <Text style={[S.tableHeaderCell, { width: "15%" }]}>Oldest Due</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>Days Overdue</Text>
      <Text style={[S.tableHeaderCell, { width: "13%", textAlign: "right" }]}>Balance Due</Text>
    </View>
  );
}

export function DelinquencyPDF({
  rows,
  hoaName,
  runDate,
}: {
  rows: DelinquencyRow[];
  hoaName: string;
  runDate: string;
}) {
  const totalAmount = rows.reduce((s, r) => s + r.open_amount, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title="Delinquency Report" />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={[S.tableCell, { color: C.green700 }]}>
              No delinquent accounts — all assessments are current.
            </Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { width: "10%" }]}>Lot {r.lot_number}</Text>
            <Text style={[S.tableCell, { width: "25%" }]}>{r.owner_name ?? "—"}</Text>
            <Text style={[S.tableCellMuted, { width: "25%" }]}>{r.email ?? r.phone ?? "—"}</Text>
            <Text style={[S.tableCellMuted, { width: "15%" }]}>{r.oldest_due_date ?? "—"}</Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right", color: daysOverdueColor(r.days_overdue) }]}>
              {r.days_overdue}
            </Text>
            <Text style={[S.tableCellBold, { width: "13%", textAlign: "right", color: C.red700 }]}>
              {fmt(r.open_amount)}
            </Text>
          </View>
        ))}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: "13%", textAlign: "right" }]}>{fmt(totalAmount)}</Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
