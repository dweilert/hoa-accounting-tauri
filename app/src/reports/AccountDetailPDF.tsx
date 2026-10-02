/**
 * Account Detail PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter, fmtAbs, fmtBal, Pill } from "./pdf-utils";

export type LedgerRow = {
  txn_date: string;
  source_type: string;
  description: string;
  amount: number;
  lot_number: string | null;
  running_balance?: number;
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
      <Text style={[S.tableHeaderCell, { width: "38%" }]}>Description</Text>
      <Text style={[S.tableHeaderCell, { width: "10%" }]}>Lot</Text>
      <Text style={[S.tableHeaderCell, { width: "13%", textAlign: "right" }]}>Amount</Text>
      <Text style={[S.tableHeaderCell, { width: "14%", textAlign: "right" }]}>Balance</Text>
    </View>
  );
}

export function AccountDetailPDF({
  rows,
  hoaName,
  runDate,
  accountName,
}: {
  rows: LedgerRow[];
  hoaName: string;
  runDate: string;
  accountName?: string | undefined;
}) {
  const title = `Account Detail${accountName ? ` — ${accountName}` : ""}`;

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={title} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No transactions for this account.</Text>
          </View>
        )}

        {rows.map((r, i) => (
          <View key={i} style={S.tableRow} wrap={false}>
            <Text style={[S.tableCell, { width: "11%" }]}>{r.txn_date}</Text>
            <View style={{ width: "14%" }}>
              {txnPill(r.source_type)}
            </View>
            <Text style={[S.tableCell, { width: "38%" }]}>{r.description}</Text>
            <Text style={[S.tableCellMuted, { width: "10%" }]}>
              {r.lot_number ? `Lot ${r.lot_number}` : "—"}
            </Text>
            <Text style={[S.tableCell, { width: "13%", textAlign: "right", color: r.amount > 0 ? C.green700 : C.red700 }]}>
              {fmtAbs(r.amount)}
            </Text>
            <Text style={[S.tableCellMono, { width: "14%", textAlign: "right", color: C.gray700 }]}>
              {r.running_balance !== undefined ? fmtBal(r.running_balance) : "—"}
            </Text>
          </View>
        ))}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
