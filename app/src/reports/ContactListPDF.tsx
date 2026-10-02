/**
 * Contact List PDF — generated via @react-pdf/renderer.
 * Multi-page handled automatically; footer pinned absolutely on every page.
 */
import { Document, Page, Text, View, StyleSheet } from "@react-pdf/renderer";
import { S, C, ReportHeader, ReportFooter } from "./pdf-utils";

export type ContactRow = {
  lot_number: string;
  owner_name: string | null;
  owner_type: string | null;
  email: string | null;
  phone: string | null;
  home_phone: string | null;
  mailing_address_1: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
};

const ls = StyleSheet.create({
  colOwner:   { width: "24%", paddingRight: 4 },
  colEmail:   { width: "30%", paddingRight: 4 },
  colPhone:   { width: "18%", paddingRight: 4 },
  colAddress: { width: "28%" },
  addrLine2:  { fontSize: 8, color: C.gray500 },
  noOwner:    { fontSize: 9, color: C.gray400, fontStyle: "italic" },
});

function TableHeader() {
  return (
    <View style={S.tableHeaderRow} fixed>
      <Text style={[S.tableHeaderCell, ls.colOwner]}>Owner</Text>
      <Text style={[S.tableHeaderCell, ls.colEmail]}>Email</Text>
      <Text style={[S.tableHeaderCell, ls.colPhone]}>Phone</Text>
      <Text style={[S.tableHeaderCell, ls.colAddress]}>Mailing Address</Text>
    </View>
  );
}

function ContactRow({ row }: { row: ContactRow }) {
  const phone = row.phone ?? row.home_phone;
  const hasOwner = !!row.owner_name;
  const cityLine = [row.city, row.state, row.postal_code].filter(Boolean).join(", ");

  return (
    <View
      style={[S.tableRow, hasOwner ? {} : S.tableRowAlt]}
      wrap={false}
    >
      <View style={ls.colOwner}>
        {hasOwner
          ? <Text style={S.tableCellBold}>{row.owner_name}</Text>
          : <Text style={ls.noOwner}>— No owner —</Text>}
      </View>
      <Text style={[S.tableCellMuted, ls.colEmail]}>{row.email ?? "—"}</Text>
      <Text style={[S.tableCellMuted, ls.colPhone]}>{phone ?? "—"}</Text>
      <View style={ls.colAddress}>
        {row.mailing_address_1
          ? <>
              <Text style={S.tableCellMuted}>{row.mailing_address_1}</Text>
              {cityLine ? <Text style={ls.addrLine2}>{cityLine}</Text> : null}
            </>
          : <Text style={S.tableCellMuted}>—</Text>}
      </View>
    </View>
  );
}

export function ContactListPDF({
  rows,
  hoaName,
  runDate,
}: {
  rows: ContactRow[];
  hoaName: string;
  runDate: string;
}) {
  return (
    <Document>
      <Page size="LETTER" style={S.page}>
        <ReportHeader runDate={runDate} hoaName={hoaName} title="Contact List" />

        <TableHeader />

        {rows.length === 0 && (
          <View style={[S.tableRow]}>
            <Text style={S.tableCellMuted}>No homeowners found.</Text>
          </View>
        )}

        {rows.map((r) => (
          <ContactRow key={r.lot_number} row={r} />
        ))}

        <ReportFooter hoaName={hoaName} />
      </Page>
    </Document>
  );
}
