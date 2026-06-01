import { getDb } from "../lib/db";

export type TransactionRule = {
  id: number;
  rule_name: string;
  description_contains: string | null;
  amount_min: number | null;
  amount_max: number | null;
  transaction_type: string | null;
  action_type: string;
  category_id: number | null;
  category_name: string | null;
  vendor_id: number | null;
  vendor_name: string | null;
  confidence_mode: "REVIEW_FIRST" | "AUTO_POST";
  active_flag: number;
  match_count: number;
  created_at: string;
};

export type TransactionRuleFormValues = {
  rule_name: string;
  description_contains: string;
  amount_min: string;
  amount_max: string;
  transaction_type: string;
  action_type: string;
  category_id: number | null;
  vendor_id: number | null;
  confidence_mode: "REVIEW_FIRST" | "AUTO_POST";
};

export async function listTransactionRules(): Promise<TransactionRule[]> {
  const db = await getDb();
  const rows = await db.select<TransactionRule[]>(`
    SELECT r.*,
           c.name AS category_name,
           v.vendor_name
    FROM bank_transaction_rules r
    LEFT JOIN categories c ON c.id = r.category_id
    LEFT JOIN vendors v ON v.id = r.vendor_id
    ORDER BY r.rule_name
  `);
  return rows;
}

export async function insertTransactionRule(values: TransactionRuleFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO bank_transaction_rules
       (rule_name, description_contains, amount_min, amount_max, transaction_type,
        action_type, category_id, vendor_id, confidence_mode)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.rule_name,
      values.description_contains || null,
      values.amount_min !== "" ? Number(values.amount_min) : null,
      values.amount_max !== "" ? Number(values.amount_max) : null,
      values.transaction_type || null,
      values.action_type,
      values.category_id ?? null,
      values.vendor_id ?? null,
      values.confidence_mode,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateTransactionRule(id: number, values: TransactionRuleFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE bank_transaction_rules
     SET rule_name = ?, description_contains = ?, amount_min = ?, amount_max = ?,
         transaction_type = ?, action_type = ?, category_id = ?, vendor_id = ?,
         confidence_mode = ?, updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.rule_name,
      values.description_contains || null,
      values.amount_min !== "" ? Number(values.amount_min) : null,
      values.amount_max !== "" ? Number(values.amount_max) : null,
      values.transaction_type || null,
      values.action_type,
      values.category_id ?? null,
      values.vendor_id ?? null,
      values.confidence_mode,
      id,
    ]
  );
}

export async function toggleRuleActive(id: number, active: boolean): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE bank_transaction_rules SET active_flag = ?, updated_at = datetime('now') WHERE id = ?",
    [active ? 1 : 0, id]
  );
}

export async function deleteTransactionRule(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM bank_transaction_rules WHERE id = ?", [id]);
}

export type RuleTestResult = {
  ruleId: number;
  ruleName: string;
  matches: boolean;
  reason: string;
};

export function testRuleAgainstDescription(
  rule: TransactionRule,
  description: string,
  amount: number
): RuleTestResult {
  const reasons: string[] = [];
  let matches = true;

  if (rule.description_contains) {
    const hit = description.toLowerCase().includes(rule.description_contains.toLowerCase());
    if (!hit) { matches = false; reasons.push(`description does not contain "${rule.description_contains}"`); }
    else reasons.push(`description contains "${rule.description_contains}"`);
  }
  if (rule.amount_min !== null && amount < rule.amount_min) {
    matches = false;
    reasons.push(`amount ${amount} < min ${rule.amount_min}`);
  }
  if (rule.amount_max !== null && amount > rule.amount_max) {
    matches = false;
    reasons.push(`amount ${amount} > max ${rule.amount_max}`);
  }

  return {
    ruleId: rule.id,
    ruleName: rule.rule_name,
    matches,
    reason: reasons.join("; ") || (matches ? "all conditions met" : "no conditions checked"),
  };
}
