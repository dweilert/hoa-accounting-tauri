/**
 * Deposits PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type DepositReportRow = {
  deposit_date: string;
  account_name: string;
  check_count: number;
  total_amount: number;
  status: string;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const W = { date: "18%", account: "57%", amount: "25%" };

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { width: W.date }]}>Date</Text>
      <Text style={[S.tableHeaderCell, { width: W.account }]}>Account</Text>
      <Text style={[S.tableHeaderCell, { width: W.amount, textAlign: "right" }]}>Amount</Text>
    </View>
  );
}

export function DepositsPDF({
  rows,
  hoaName,
  runDate,
  year,
}: {
  rows: DepositReportRow[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const totalAmount = rows.reduce((s, r) => s + r.total_amount, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Deposits — ${year}`} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No deposits for {year}.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell,     { width: W.date }]}>{r.deposit_date}</Text>
            <Text style={[S.tableCellMuted, { width: W.account }]}>{r.account_name}</Text>
            <Text style={[S.tableCellMono,  { width: W.amount, textAlign: "right", color: C.green700 }]}>
              {fmt(r.total_amount)}
            </Text>
          </View>
        ))}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: W.amount, textAlign: "right", color: C.green700, fontFamily: "Courier" }]}>
              {fmt(totalAmount)}
            </Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
