/**
 * Shared styles, colors, and layout components for all HOA report PDFs.
 * Uses @react-pdf/renderer — layout is exact, no browser print quirks.
 *
 * Every PDF report:
 *   - Letter size (8.5 × 11in), 0.5in margins
 *   - Page header: run date top-left, HOA name centered, report title centered
 *   - Dark navy table header (slate-800 equivalent)
 *   - Footer: HOA name left, "Page N of M" right — pinned via position:absolute
 */
import { StyleSheet, Text, View } from "@react-pdf/renderer";

// ── Color palette (matches Tailwind classes used on screen) ──────────────────
export const C = {
  navyBg:    "#1e293b", // slate-800 — table header background
  white:     "#ffffff",
  gray900:   "#111827",
  gray700:   "#374151",
  gray500:   "#6b7280",
  gray400:   "#9ca3af",
  gray300:   "#d1d5db",
  gray200:   "#e5e7eb",
  gray100:   "#f3f4f6",
  gray50:    "#f9fafb",
  red100:    "#fee2e2",
  red700:    "#b91c1c",
  green100:  "#dcfce7",
  green700:  "#15803d",
  redBal:    "#dc2626", // negative/owed balances
  greenBal:  "#16a34a", // credit balances
};

// ── Page geometry ─────────────────────────────────────────────────────────────
export const PAGE_PAD = "0.5in";      // uniform margin on all sides
export const FOOTER_H  = 18;          // footer height in pt (approx 0.25in)

// ── Base styles shared across all PDFs ───────────────────────────────────────
export const S = StyleSheet.create({
  page: {
    paddingTop:    "0.5in",
    paddingBottom: "0.75in",   // extra room for absolute-positioned footer
    paddingLeft:   "0.5in",
    paddingRight:  "0.5in",
    fontSize:      9,
    fontFamily:    "Helvetica",
    color:         C.gray900,
    backgroundColor: C.white,
  },

  // ── Report header (date / HOA name / title) ──────────────────────────────
  reportHeader: {
    marginBottom:      10,
    paddingBottom:     8,
    borderBottomWidth: 1.5,
    borderBottomColor: C.gray400,
  },
  runDate: {
    fontSize:    7,
    color:       C.gray400,
    marginBottom: 3,
  },
  hoaName: {
    fontSize:    9,
    fontFamily:  "Helvetica-Bold",
    textAlign:   "center",
    marginBottom: 2,
  },
  reportTitle: {
    fontSize:    12,
    fontFamily:  "Helvetica-Bold",
    textAlign:   "center",
  },
  continued: {
    fontSize:    9,
    color:       C.gray500,
    textAlign:   "center",
    marginBottom: 6,
  },

  // ── Table primitives ──────────────────────────────────────────────────────
  tableHeaderRow: {
    flexDirection:    "row",
    backgroundColor:  C.navyBg,
    paddingHorizontal: 8,
    paddingVertical:   5,
  },
  tableHeaderCell: {
    fontSize:    8,
    color:       C.white,
    fontFamily:  "Helvetica-Bold",
  },
  tableRow: {
    flexDirection:   "row",
    paddingHorizontal: 8,
    paddingVertical:   4,
    borderBottomWidth: 0.5,
    borderBottomColor: C.gray100,
  },
  tableRowAlt: {              // for "no owner" / empty rows
    backgroundColor: C.gray50,
  },
  tableCell: {
    fontSize: 9,
    color:    C.gray700,
  },
  tableCellMuted: {
    fontSize: 9,
    color:    C.gray500,
  },
  tableCellBold: {
    fontSize:   9,
    fontFamily: "Helvetica-Bold",
    color:      C.gray900,
  },
  tableCellMono: {
    fontSize:   9,
    fontFamily: "Courier",
    color:      C.gray700,
  },

  // ── Footer (absolute-positioned so it's always at page bottom) ───────────
  footer: {
    position:  "absolute",
    bottom:    "0.4in",
    left:      "0.5in",
    right:     "0.5in",
    flexDirection:    "row",
    justifyContent:   "space-between",
    paddingTop:       4,
    borderTopWidth:   0.5,
    borderTopColor:   C.gray300,
    fontSize:         7,
    color:            C.gray500,
  },
});

// ── Shared report header component ───────────────────────────────────────────
export function ReportHeader({
  runDate,
  hoaName,
  title,
  continued = false,
}: {
  runDate: string;
  hoaName: string;
  title: string;
  continued?: boolean;
}) {
  if (continued) {
    return (
      <View style={S.reportHeader}>
        {hoaName ? <Text style={S.hoaName}>{hoaName}</Text> : null}
        <Text style={S.continued}>{title} (continued)</Text>
      </View>
    );
  }
  return (
    <View style={S.reportHeader}>
      <Text style={S.runDate}>{runDate}</Text>
      {hoaName ? <Text style={S.hoaName}>{hoaName}</Text> : null}
      <Text style={S.reportTitle}>{title}</Text>
    </View>
  );
}

// ── Page footer component (fixed=true repeats on every page) ─────────────────
export function ReportFooter({ hoaName }: { hoaName: string }) {
  return (
    <View style={S.footer} fixed>
      <Text>{hoaName}</Text>
      <Text render={({ pageNumber, totalPages }) => `Page ${pageNumber} of ${totalPages}`} />
    </View>
  );
}

// ── Balance formatting helpers ────────────────────────────────────────────────
export function fmtBal(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `($${formatted})` : `$${formatted}`;
}

export function fmtAbs(n: number): string {
  const abs = Math.abs(n);
  return "$" + abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function balColor(n: number): string {
  return n < 0 ? C.redBal : n > 0 ? C.greenBal : C.gray700;
}

export function fmtChargeType(s: string | null | undefined): string {
  if (!s) return "Charge";
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase().replace(/_/g, " ");
}

// ── Pill component (charge type / payment badges) ────────────────────────────
export function Pill({
  label,
  bgColor,
  textColor,
}: {
  label: string;
  bgColor: string;
  textColor: string;
}) {
  return (
    <View
      style={{
        backgroundColor: bgColor,
        borderRadius:    999,
        paddingHorizontal: 5,
        paddingVertical:   1,
        alignSelf:       "flex-start",
      }}
    >
      <Text style={{ fontSize: 7.5, color: textColor, fontFamily: "Helvetica-Bold" }}>
        {label}
      </Text>
    </View>
  );
}
