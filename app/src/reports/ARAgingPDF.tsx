/**
 * Accounts Receivable Aging PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type AgingBucket = {
  lot_number: string;
  owner_name: string | null;
  current: number;
  d30: number;
  d60: number;
  d90plus: number;
  total: number;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { width: "12%" }]}>Lot</Text>
      <Text style={[S.tableHeaderCell, { width: "28%" }]}>Owner</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>Current 0-30d</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>31-60d</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>61-90d</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>90d+</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>Total</Text>
    </View>
  );
}

export function ARAgingPDF({
  rows,
  hoaName,
  runDate,
}: {
  rows: AgingBucket[];
  hoaName: string;
  runDate: string;
}) {
  const totalCurrent = rows.reduce((s, r) => s + r.current, 0);
  const totalD30 = rows.reduce((s, r) => s + r.d30, 0);
  const totalD60 = rows.reduce((s, r) => s + r.d60, 0);
  const totalD90plus = rows.reduce((s, r) => s + r.d90plus, 0);
  const totalTotal = rows.reduce((s, r) => s + r.total, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title="Accounts Receivable Aging" />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No outstanding balances.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { width: "12%" }]}>Lot {r.lot_number}</Text>
            <Text style={[S.tableCell, { width: "28%" }]}>{r.owner_name ?? "—"}</Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right" }]}>
              {r.current === 0 ? "—" : fmt(r.current)}
            </Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right" }]}>
              {r.d30 === 0 ? "—" : fmt(r.d30)}
            </Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right", color: r.d60 > 0 ? "#ea580c" : C.gray700 }]}>
              {r.d60 === 0 ? "—" : fmt(r.d60)}
            </Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right", color: r.d90plus > 0 ? C.red700 : C.gray700 }]}>
              {r.d90plus === 0 ? "—" : fmt(r.d90plus)}
            </Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>
              {fmt(r.total)}
            </Text>
          </View>
        ))}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { width: "12%" }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: "28%" }]}></Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>{fmt(totalCurrent)}</Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>{fmt(totalD30)}</Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>{fmt(totalD60)}</Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>{fmt(totalD90plus)}</Text>
            <Text style={[S.tableCellBold, { width: "12%", textAlign: "right" }]}>{fmt(totalTotal)}</Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
