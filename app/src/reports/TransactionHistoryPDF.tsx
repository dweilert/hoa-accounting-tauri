/**
 * Transaction History PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter, fmtAbs, Pill } from "./pdf-utils";

export type TxnRow = {
  txn_date: string;
  source_type: string;
  account_name: string | null;
  description: string;
  lot_number: string | null;
  amount: number;
};

const SOURCE_LABELS: Record<string, string> = {
  PAYMENT:      "Payment",
  BILL_PAYMENT: "Bill Payment",
  INCOME:       "Income",
};

function txnPill(sourceType: string) {
  switch (sourceType) {
    case "PAYMENT":
      return <Pill label="Payment"      bgColor={C.green100} textColor={C.green700} />;
    case "BILL_PAYMENT":
      return <Pill label="Bill Payment" bgColor={C.red100}   textColor={C.red700}   />;
    case "INCOME":
      return <Pill label="Income"       bgColor="#dbeafe"    textColor="#1d4ed8"    />;
    default:
      return <Pill label={SOURCE_LABELS[sourceType] ?? sourceType} bgColor={C.gray100} textColor={C.gray700} />;
  }
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { width: "11%" }]}>Date</Text>
      <Text style={[S.tableHeaderCell, { width: "14%" }]}>Type</Text>
      <Text style={[S.tableHeaderCell, { width: "35%" }]}>Description</Text>
      <Text style={[S.tableHeaderCell, { width: "20%" }]}>Account</Text>
      <Text style={[S.tableHeaderCell, { width: "8%" }]}>Lot</Text>
      <Text style={[S.tableHeaderCell, { width: "12%", textAlign: "right" }]}>Amount</Text>
    </View>
  );
}

export function TransactionHistoryPDF({
  rows,
  hoaName,
  runDate,
}: {
  rows: TxnRow[];
  hoaName: string;
  runDate: string;
}) {
  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title="Transaction History" />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No transactions yet.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { width: "11%" }]}>{r.txn_date}</Text>
            <View style={{ width: "14%" }}>
              {txnPill(r.source_type)}
            </View>
            <Text style={[S.tableCell, { width: "35%" }]}>{r.description}</Text>
            <Text style={[S.tableCellMuted, { width: "20%" }]}>{r.account_name ?? "—"}</Text>
            <Text style={[S.tableCellMuted, { width: "8%" }]}>
              {r.lot_number ? `Lot ${r.lot_number}` : "—"}
            </Text>
            <Text style={[S.tableCell, { width: "12%", textAlign: "right", color: r.amount > 0 ? C.green700 : C.red700 }]}>
              {fmtAbs(r.amount)}
            </Text>
          </View>
        ))}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
