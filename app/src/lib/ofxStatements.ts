export type OFXStatement = { acctid: string; text: string };

export function splitStatements(text: string): OFXStatement[] {
  const found: OFXStatement[] = [];
  const re = /<(STMTRS|CCSTMTRS)>[\s\S]*?<\/\1>/gi;
  for (const m of text.matchAll(re)) {
    const acctid = /<ACCTID>([^<\r\n]+)/i.exec(m[0])?.[1]?.trim() ?? "";
    found.push({ acctid, text: m[0] });
  }
  if (found.length > 0) return found;
  const acctid = /<ACCTID>([^<\r\n]+)/i.exec(text)?.[1]?.trim() ?? "";
  return [{ acctid, text }];
}

export function last4(acctid: string): string {
  return acctid.replace(/\s/g, "").slice(-4);
}
