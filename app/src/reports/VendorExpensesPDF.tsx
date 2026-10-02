/**
 * Vendor Expenses PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type VendorExpenseRow = {
  vendor_name: string;
  paid: number;
  open: number;
  total: number;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { flex: 1 }]}>Vendor</Text>
      <Text style={[S.tableHeaderCell, { width: "20%", textAlign: "right" }]}>Paid</Text>
      <Text style={[S.tableHeaderCell, { width: "20%", textAlign: "right" }]}>Open</Text>
      <Text style={[S.tableHeaderCell, { width: "22%", textAlign: "right" }]}>Total Invoiced</Text>
    </View>
  );
}

export function VendorExpensesPDF({
  rows,
  hoaName,
  runDate,
  year,
}: {
  rows: VendorExpenseRow[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const totalPaid = rows.reduce((s, r) => s + r.paid, 0);
  const totalOpen = rows.reduce((s, r) => s + r.open, 0);
  const totalTotal = rows.reduce((s, r) => s + r.total, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Vendor Expenses — ${year}`} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No vendor invoices for {year}.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { flex: 1 }]}>{r.vendor_name}</Text>
            <Text style={[S.tableCell, { width: "20%", textAlign: "right", color: C.green700 }]}>
              {fmt(r.paid)}
            </Text>
            <Text style={[S.tableCell, { width: "20%", textAlign: "right", color: r.open > 0 ? "#ea580c" : C.gray500 }]}>
              {r.open === 0 ? "—" : fmt(r.open)}
            </Text>
            <Text style={[S.tableCellBold, { width: "22%", textAlign: "right" }]}>
              {fmt(r.total)}
            </Text>
          </View>
        ))}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: "20%", textAlign: "right" }]}>{fmt(totalPaid)}</Text>
            <Text style={[S.tableCellBold, { width: "20%", textAlign: "right" }]}>{fmt(totalOpen)}</Text>
            <Text style={[S.tableCellBold, { width: "22%", textAlign: "right" }]}>{fmt(totalTotal)}</Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
