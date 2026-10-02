/**
 * Budget vs Actual PDF — generated via @react-pdf/renderer.
 */
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type BvARow = {
  category_name: string;
  budget_amount: number;
  actual_amount: number;
  variance: number;
};

function fmt(n: number): string {
  return "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pctUsedColor(pct: number): string {
  if (pct > 100) return C.red700;
  if (pct > 80) return "#ea580c";
  return C.green700;
}

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, { flex: 1 }]}>Category</Text>
      <Text style={[S.tableHeaderCell, { width: "16%", textAlign: "right" }]}>Budget</Text>
      <Text style={[S.tableHeaderCell, { width: "16%", textAlign: "right" }]}>Actual</Text>
      <Text style={[S.tableHeaderCell, { width: "16%", textAlign: "right" }]}>Variance</Text>
      <Text style={[S.tableHeaderCell, { width: "14%", textAlign: "right" }]}>% Used</Text>
    </View>
  );
}

export function BudgetVsActualPDF({
  rows,
  hoaName,
  runDate,
  year,
}: {
  rows: BvARow[];
  hoaName: string;
  runDate: string;
  year: number;
}) {
  const totalBudget = rows.reduce((s, r) => s + r.budget_amount, 0);
  const totalActual = rows.reduce((s, r) => s + r.actual_amount, 0);
  const totalVariance = rows.reduce((s, r) => s + r.variance, 0);

  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title={`Budget vs Actual — ${year}`} />

        <TableHeader />

        {rows.length === 0 && (
          <View style={S.tableRow}>
            <Text style={S.tableCellMuted}>No budget or expense data for {year}.</Text>
          </View>
        )}

        {rows.map((r, i) => {
          const pct = r.budget_amount > 0 ? (r.actual_amount / r.budget_amount) * 100 : null;
          const pctLabel = pct !== null ? pct.toFixed(0) + "%" : "—";
          const pctColor = pct !== null ? pctUsedColor(pct) : C.gray500;

          return (
            <View key={i} style={S.tableRow} wrap={false}>
              <Text style={[S.tableCell, { flex: 1 }]}>{r.category_name}</Text>
              <Text style={[S.tableCell, { width: "16%", textAlign: "right" }]}>{fmt(r.budget_amount)}</Text>
              <Text style={[S.tableCell, { width: "16%", textAlign: "right", color: C.red700 }]}>{fmt(r.actual_amount)}</Text>
              <Text style={[S.tableCell, { width: "16%", textAlign: "right", color: r.variance >= 0 ? C.green700 : C.red700 }]}>
                {fmt(r.variance)}
              </Text>
              <Text style={[S.tableCell, { width: "14%", textAlign: "right", color: pctColor }]}>
                {pctLabel}
              </Text>
            </View>
          );
        })}

        {rows.length > 0 && (
          <View style={[S.tableRow, { backgroundColor: C.gray50, borderTopWidth: 1, borderTopColor: C.gray300 }]}>
            <Text style={[S.tableCellBold, { flex: 1 }]}>Total</Text>
            <Text style={[S.tableCellBold, { width: "16%", textAlign: "right" }]}>{fmt(totalBudget)}</Text>
            <Text style={[S.tableCellBold, { width: "16%", textAlign: "right" }]}>{fmt(totalActual)}</Text>
            <Text style={[S.tableCellBold, { width: "16%", textAlign: "right", color: totalVariance >= 0 ? C.green700 : C.red700 }]}>
              {fmt(totalVariance)}
            </Text>
            <Text style={[S.tableCellBold, { width: "14%" }]}></Text>
          </View>
        )}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
