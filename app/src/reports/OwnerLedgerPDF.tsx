/**
 * Owner Ledger PDF — generated via @react-pdf/renderer.
 * Layout mirrors the screen report exactly.
 * Multi-page handled automatically by react-pdf; no manual row splitting needed.
 */
import { Document, Page, Text, View, StyleSheet } from "@react-pdf/renderer";
import {
  S, C,
  ReportHeader, ReportFooter,
  fmtBal, fmtAbs, balColor, fmtChargeType, Pill,
} from "./pdf-utils";

// ── Types (mirror ReportsScreen.tsx) ─────────────────────────────────────────
export type OwnerLedgerRow = {
  txn_date: string;
  type: string;
  charge_type: string | null;
  description: string;
  amount: number;
  running_balance: number;
};

export type OLBeginItem = { label: string; amount: number };

export type OLOwnerInfo = {
  display_name: string;
  mailing_address_1: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  phone: string | null;
  email: string | null;
  lot_numbers: string[];
};

export type OwnerLedgerResult = {
  rows: OwnerLedgerRow[];
  beginningBalance: number;
  beginBalanceDetail: OLBeginItem[];
};

// ── Local styles ──────────────────────────────────────────────────────────────
const ls = StyleSheet.create({
  // Section boxes (Owners, Summary strip, Begin Balance Detail)
  sectionBox: {
    borderWidth:   0.5,
    borderColor:   C.gray300,
    borderRadius:  3,
    marginBottom:  8,
    overflow:      "hidden",
  },
  sectionLabel: {
    backgroundColor: C.gray50,
    paddingHorizontal: 8,
    paddingVertical:   4,
    borderBottomWidth: 0.5,
    borderBottomColor: C.gray200,
    fontSize:   8,
    fontFamily: "Helvetica-Bold",
    color:      C.gray500,
    textTransform: "uppercase",
  },

  // Owners grid
  ownersGrid: {
    flexDirection: "row",
    flexWrap:      "wrap",
    padding:       8,
    gap:           8,
  },
  ownerCard: {
    width: "48%",
  },
  ownerName: {
    fontSize:   9,
    fontFamily: "Helvetica-Bold",
    color:      C.gray900,
  },
  ownerDetail: {
    fontSize: 8,
    color:    C.gray500,
    marginTop: 1,
  },

  // Summary strip columns
  summaryGrid: {
    flexDirection: "row",
  },
  summaryCell: {
    flex:             1,
    paddingHorizontal: 8,
    paddingVertical:   4,
    borderRightWidth:  0.5,
    borderRightColor:  C.gray200,
  },
  summaryCellLast: {
    flex:             1,
    paddingHorizontal: 8,
    paddingVertical:   4,
  },
  summaryLabel: {
    fontSize: 7.5,
    color:    C.gray500,
    fontFamily: "Helvetica-Bold",
    textTransform: "uppercase",
    marginBottom: 2,
  },
  summaryValue: {
    fontSize:   9,
    fontFamily: "Helvetica-Bold",
    color:      C.gray900,
  },

  // Transaction table columns
  colDate:    { width: "10%", paddingRight: 2 },
  colType:    { width: "14%", paddingRight: 2 },
  colDesc:    { width: "36%", paddingRight: 2 },
  colCharge:  { width: "13%", textAlign: "right", paddingRight: 4 },
  colPayment: { width: "13%", textAlign: "right", paddingRight: 4 },
  colBalance: { width: "14%", textAlign: "right" },

  // Closing balance footer row
  closingRow: {
    flexDirection:   "row",
    paddingHorizontal: 8,
    paddingVertical:   5,
    borderTopWidth:    1.5,
    borderTopColor:    C.gray300,
  },
  closingLabel: {
    flex:       1,
    textAlign:  "right",
    fontFamily: "Helvetica-Bold",
    fontSize:   9,
    color:      C.gray900,
    paddingRight: 4,
  },
  closingValue: {
    width:      "14%",
    textAlign:  "right",
    fontFamily: "Helvetica-Bold",
    fontSize:   9,
    fontFamily2: "Courier",
  },
});

// ── Sub-components ────────────────────────────────────────────────────────────

function OwnersBox({ owners }: { owners: OLOwnerInfo[] }) {
  if (owners.length === 0) return null;
  return (
    <View style={ls.sectionBox}>
      <Text style={ls.sectionLabel}>Owners</Text>
      <View style={ls.ownersGrid}>
        {owners.map((o, i) => {
          const cityLine = [o.city, o.state, o.postal_code].filter(Boolean).join(" ");
          return (
            <View key={i} style={ls.ownerCard}>
              <Text style={ls.ownerName}>{o.display_name}</Text>
              {o.email      && <Text style={ls.ownerDetail}>Email: {o.email}</Text>}
              {o.phone      && <Text style={ls.ownerDetail}>Phone: {o.phone}</Text>}
              {o.mailing_address_1 && <Text style={ls.ownerDetail}>{o.mailing_address_1}</Text>}
              {cityLine     && <Text style={ls.ownerDetail}>{cityLine}</Text>}
            </View>
          );
        })}
      </View>
    </View>
  );
}

function SummaryStrip({
  year, duesBal, assessBal, closingBal,
}: {
  year: number; duesBal: number; assessBal: number; closingBal: number;
}) {
  const cells = [
    { label: "Year",                        value: String(year),          color: C.gray900 },
    { label: "Opening Dues Balance",        value: fmtBal(duesBal),       color: balColor(duesBal) },
    { label: "Opening Assessments Balance", value: fmtBal(assessBal),     color: balColor(assessBal) },
    { label: "Closing Balance",             value: fmtBal(closingBal),    color: balColor(closingBal) },
  ];
  return (
    <View style={ls.sectionBox}>
      <View style={ls.summaryGrid}>
        {cells.map((c, i) => (
          <View key={i} style={i < 3 ? ls.summaryCell : ls.summaryCellLast}>
            <Text style={ls.summaryLabel}>{c.label}</Text>
            <Text style={[ls.summaryValue, { color: c.color }]}>{c.value}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function BeginBalanceDetail({
  items, total,
}: {
  items: OLBeginItem[]; total: number;
}) {
  if (items.length === 0) return null;
  return (
    <View style={ls.sectionBox}>
      <Text style={ls.sectionLabel}>Beginning Balance Detail</Text>
      {/* Header */}
      <View style={[S.tableRow, { backgroundColor: C.gray50 }]}>
        <Text style={[S.tableCellMuted, { flex: 1, fontSize: 8 }]}>Charge Type</Text>
        <Text style={[S.tableCellMuted, { width: "25%", textAlign: "right", fontSize: 8 }]}>Balance</Text>
      </View>
      {items.map((item, i) => (
        <View key={i} style={S.tableRow}>
          <Text style={[S.tableCell, { flex: 1 }]}>Prior Balance — {fmtChargeType(item.label)}</Text>
          <Text style={[S.tableCellMono, { width: "25%", textAlign: "right", color: balColor(item.amount) }]}>
            {fmtBal(item.amount)}
          </Text>
        </View>
      ))}
      {/* Total row */}
      <View style={[S.tableRow, { borderTopWidth: 0.5, borderTopColor: C.gray200 }]}>
        <Text style={[S.tableCellBold, { flex: 1, textAlign: "right" }]}>Total Opening Balance</Text>
        <Text style={[S.tableCellMono, { width: "25%", textAlign: "right", fontFamily: "Helvetica-Bold", color: balColor(total) }]}>
          {fmtBal(total)}
        </Text>
      </View>
    </View>
  );
}

function TxnTableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, ls.colDate]}>Date</Text>
      <Text style={[S.tableHeaderCell, ls.colType]}>Type</Text>
      <Text style={[S.tableHeaderCell, ls.colDesc]}>Description</Text>
      <Text style={[S.tableHeaderCell, ls.colCharge]}>Charge</Text>
      <Text style={[S.tableHeaderCell, ls.colPayment]}>Payment</Text>
      <Text style={[S.tableHeaderCell, ls.colBalance]}>Balance</Text>
    </View>
  );
}

function TxnRow({ row }: { row: OwnerLedgerRow }) {
  const isPayment = row.type === "PAYMENT";
  return (
    <View style={S.tableRow} wrap={false}>
      <Text style={[S.tableCell, ls.colDate]}>{row.txn_date}</Text>
      <View style={ls.colType}>
        {isPayment
          ? <Pill label="Payment"                       bgColor={C.green100} textColor={C.green700} />
          : <Pill label={fmtChargeType(row.charge_type)} bgColor={C.red100}   textColor={C.red700}   />
        }
      </View>
      <Text style={[S.tableCell, ls.colDesc]}>{row.description}</Text>
      <Text style={[S.tableCellMono, ls.colCharge]}>
        {row.amount < 0 ? fmtAbs(row.amount) : ""}
      </Text>
      <Text style={[S.tableCellMono, ls.colPayment]}>
        {row.amount >= 0 ? fmtAbs(row.amount) : ""}
      </Text>
      <Text style={[S.tableCellMono, ls.colBalance, { color: balColor(row.running_balance) }]}>
        {fmtBal(row.running_balance)}
      </Text>
    </View>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────
export function OwnerLedgerPDF({
  result,
  ownerDetails,
  hoaName,
  runDate,
  year,
}: {
  result: OwnerLedgerResult;
  ownerDetails: OLOwnerInfo[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const { rows, beginningBalance, beginBalanceDetail } = result;

  const lastRow = rows.length > 0 ? rows[rows.length - 1] : null;
  const closingBal = lastRow ? lastRow.running_balance : beginningBalance;
  const duesBal   = beginBalanceDetail.filter(i => i.label === "DUES").reduce((s, i) => s + i.amount, 0);
  const assessBal = beginBalanceDetail.filter(i => i.label !== "DUES" && i.label !== "Prior Payments").reduce((s, i) => s + i.amount, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Owner Ledger — ${year}`} />

        <OwnersBox owners={ownerDetails} />

        <SummaryStrip
          year={year}
          duesBal={duesBal}
          assessBal={assessBal}
          closingBal={closingBal}
        />

        <BeginBalanceDetail items={beginBalanceDetail} total={beginningBalance} />

        <TxnTableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={[S.tableCellMuted, { flex: 1, textAlign: "center" }]}>
              No transactions for {year}.
            </Text>
          </View>
        )}

        {rows.map((r, i) => <TxnRow key={i} row={r} />)}

        {/* Closing balance row */}
        {rows.length > 0 && (
          <View style={ls.closingRow}>
            <Text style={ls.closingLabel}>Closing Balance</Text>
            <Text style={[ls.closingValue, { color: balColor(closingBal) }]}>
              {fmtBal(closingBal)}
            </Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
