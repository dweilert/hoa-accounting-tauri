import { getDb } from "../lib/db";
import { listCandidateDepositBatches, linkDepositToTxn } from "./depositRepo";

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
  bank_account_id: number | null;
  bank_account_name: string | null;
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
  bank_account_id: number | null;
  confidence_mode: "REVIEW_FIRST" | "AUTO_POST";
};

export async function listTransactionRules(): Promise<TransactionRule[]> {
  const db = await getDb();
  const rows = await db.select<TransactionRule[]>(`
    SELECT r.*,
           c.name AS category_name,
           v.vendor_name,
           ba.account_name AS bank_account_name
    FROM bank_transaction_rules r
    LEFT JOIN categories c ON c.id = r.category_id
    LEFT JOIN vendors v ON v.id = r.vendor_id
    LEFT JOIN bank_accounts ba ON ba.id = r.bank_account_id
    ORDER BY r.rule_name
  `);
  return rows;
}

export async function insertTransactionRule(values: TransactionRuleFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO bank_transaction_rules
       (rule_name, description_contains, amount_min, amount_max, transaction_type,
        action_type, category_id, vendor_id, bank_account_id, confidence_mode)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.rule_name,
      values.description_contains || null,
      values.amount_min !== "" ? Number(values.amount_min) : null,
      values.amount_max !== "" ? Number(values.amount_max) : null,
      values.transaction_type || null,
      values.action_type,
      values.category_id ?? null,
      values.vendor_id ?? null,
      values.bank_account_id ?? null,
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
         bank_account_id = ?, confidence_mode = ?, updated_at = datetime('now')
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
      values.bank_account_id ?? null,
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

export type RuleConflict = {
  kind: "duplicate" | "subset_shadowed" | "subset_shadows";
  otherRuleId: number;
  otherRuleName: string;
  message: string;
};

export async function checkRuleConflicts(
  description: string,
  excludeId?: number
): Promise<RuleConflict[]> {
  if (!description.trim()) return [];
  const db = await getDb();
  const others = await db.select<{ id: number; rule_name: string; description_contains: string | null }[]>(
    "SELECT id, rule_name, description_contains FROM bank_transaction_rules WHERE active_flag = 1 AND description_contains IS NOT NULL AND description_contains != ''",
  );
  const conflicts: RuleConflict[] = [];
  const needle = description.toLowerCase().trim();
  for (const r of others) {
    if (excludeId !== undefined && r.id === excludeId) continue;
    const hay = (r.description_contains ?? "").toLowerCase().trim();
    if (hay === needle) {
      conflicts.push({
        kind: "duplicate",
        otherRuleId: r.id,
        otherRuleName: r.rule_name,
        message: `Exact duplicate of "${r.rule_name}" — only the lower-ID rule will ever fire.`,
      });
    } else if (hay.includes(needle)) {
      // existing rule's description contains the new rule's description → new rule is more general → would shadow existing
      conflicts.push({
        kind: "subset_shadows",
        otherRuleId: r.id,
        otherRuleName: r.rule_name,
        message: `"${r.rule_name}" (desc: "${r.description_contains}") contains "${description}" — if this rule has a lower ID it will shadow that rule.`,
      });
    } else if (needle.includes(hay)) {
      // new rule's description contains existing rule's description → existing is more general → would shadow new
      conflicts.push({
        kind: "subset_shadowed",
        otherRuleId: r.id,
        otherRuleName: r.rule_name,
        message: `"${r.rule_name}" (desc: "${r.description_contains}") is a substring of "${description}" — it will always fire first if its ID is lower, so this rule may never match.`,
      });
    }
  }
  return conflicts;
}

// ── Apply rules to pending transactions ──────────────────────────────────────

export type ApplyRulesResult = {
  total: number;     // UNVALIDATED transactions checked
  matched: number;   // transactions classified by AUTO_POST rules
  reviewed: number;  // transactions flagged by REVIEW_FIRST rules (not auto-validated)
  errors: { txn_id: number; rule_name: string; error: string }[];
  details: { txn_id: number; txn_desc: string; rule_name: string; auto: boolean; action_type: string }[];
};

export async function applyRulesToPending(
  bankAccountId?: number,
  dryRun = true,
  approvedIds?: Set<number>
): Promise<ApplyRulesResult> {
  const db = await getDb();

  const accountFilter = bankAccountId ? "AND bank_account_id = ?" : "";
  const params: (number | string)[] = bankAccountId ? [bankAccountId] : [];

  const txns = await db.select<{ id: number; bank_account_id: number; description: string; amount: number; transaction_type: string | null; transaction_date: string }[]>(
    `SELECT id, bank_account_id, COALESCE(description, '') AS description, amount, transaction_type, transaction_date
     FROM bank_transactions
     WHERE validation_status = 'UNVALIDATED' ${accountFilter}
     ORDER BY transaction_date DESC`,
    params
  );

  const rules = await db.select<TransactionRule[]>(`
    SELECT r.*, c.name AS category_name, v.vendor_name, ba.account_name AS bank_account_name
    FROM bank_transaction_rules r
    LEFT JOIN categories c ON c.id = r.category_id
    LEFT JOIN vendors v ON v.id = r.vendor_id
    LEFT JOIN bank_accounts ba ON ba.id = r.bank_account_id
    WHERE r.active_flag = 1
    ORDER BY r.id
  `);

  const details: ApplyRulesResult["details"] = [];
  const errors: ApplyRulesResult["errors"] = [];
  let matched = 0;
  let reviewed = 0;

  for (const txn of txns) {
    for (const rule of rules) {
      // Skip rule if it's scoped to a different bank account
      if (rule.bank_account_id !== null && rule.bank_account_id !== txn.bank_account_id) continue;
      const result = testRuleAgainstDescription(rule, txn.description, txn.amount);
      if (!result.matches) continue;

      const auto = rule.confidence_mode === "AUTO_POST";
      details.push({ txn_id: txn.id, txn_desc: txn.description, rule_name: rule.rule_name, auto, action_type: rule.action_type });

      if (!dryRun && auto && (!approvedIds || approvedIds.has(txn.id))) {
        try {
          if (rule.action_type === "IGNORE") {
            await db.execute(
              "UPDATE bank_transactions SET validation_status = 'IGNORED' WHERE id = ?",
              [txn.id]
            );
          } else if ((rule.action_type === "CATEGORIZE" || rule.action_type === "LINK_EXPENSE") && rule.category_id !== null) {
            const desc = rule.action_type === "LINK_EXPENSE" && rule.vendor_name
              ? `${rule.vendor_name} — ${txn.description}`
              : txn.description || null;
            const insertResult = await db.execute(
              `INSERT INTO income_batches (income_date, bank_account_id, category_id, amount, description)
               VALUES (?, ?, ?, ?, ?)`,
              [txn.transaction_date, txn.bank_account_id, rule.category_id, txn.amount, desc]
            );
            const batchId = insertResult.lastInsertId;
            if (batchId) {
              await db.execute(
                `INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
                 VALUES (?, 'INCOME_BATCH', ?)`,
                [txn.id, batchId]
              );
            }
            await db.execute(
              "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
              [txn.id]
            );
          } else {
            // No category configured — still mark VALIDATED so it doesn't re-process
            await db.execute(
              "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
              [txn.id]
            );
          }
          await db.execute(
            "UPDATE bank_transaction_rules SET match_count = match_count + 1, updated_at = datetime('now') WHERE id = ?",
            [rule.id]
          );
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`applyRulesToPending: txn ${txn.id} rule ${rule.id} failed:`, err);
          errors.push({ txn_id: txn.id, rule_name: rule.rule_name, error: msg });
        }
      }

      if (auto) matched++; else reviewed++;
      break; // first matching rule wins per transaction
    }

    // No rule matched — fall through to deposit batch matching for positive amounts
    const ruleMatched = details.some((d) => d.txn_id === txn.id);
    if (!ruleMatched && txn.amount > 0) {
      try {
        const candidates = await listCandidateDepositBatches(
          txn.bank_account_id, txn.amount, txn.transaction_date
        );
        const qualified = candidates.filter(
          (c) => c.status === "POSTED" &&
                 c.bank_transaction_id === null &&
                 (c.same_amount_count === 1 || c.days_diff <= 2)
        );
        if (qualified.length === 1 && qualified[0]) {
          const batch = qualified[0];
          const reason = batch.same_amount_count === 1 && batch.days_diff <= 2
            ? "unique amount + ≤2 days"
            : batch.same_amount_count === 1 ? "unique amount" : "≤2 days";
          details.push({
            txn_id: txn.id,
            txn_desc: txn.description,
            rule_name: `Deposit Match (${reason})`,
            auto: true,
            action_type: "DEPOSIT_MATCH",
          });
          matched++;
          if (!dryRun && (!approvedIds || approvedIds.has(txn.id))) {
            await linkDepositToTxn(batch.id, txn.id);
            await db.execute(
              "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
              [txn.id]
            );
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.error(`applyRulesToPending: deposit fallback txn ${txn.id} failed:`, err);
        errors.push({ txn_id: txn.id, rule_name: "Deposit Match", error: msg });
      }
    }
  }

  return { total: txns.length, matched, reviewed, errors, details };
}

export async function revertValidated(bankAccountId?: number): Promise<number> {
  const db = await getDb();
  const accountFilter = bankAccountId ? "AND bank_account_id = ?" : "";
  const params: (number | string)[] = bankAccountId ? [bankAccountId] : [];
  const result = await db.execute(
    `UPDATE bank_transactions SET validation_status = 'UNVALIDATED'
     WHERE validation_status IN ('VALIDATED', 'IGNORED') ${accountFilter}`,
    params
  );
  return result.rowsAffected ?? 0;
}

export function testRuleAgainstDescription(
  rule: TransactionRule,
  description: string,
  amount: number
): RuleTestResult {
  // Description is a SUFFICIENT condition: if set and matches, rule fires immediately.
  // Amount filters only apply when there is no description condition.
  if (rule.description_contains) {
    const hit = description.toLowerCase().includes(rule.description_contains.toLowerCase());
    return {
      ruleId: rule.id,
      ruleName: rule.rule_name,
      matches: hit,
      reason: hit
        ? `description contains "${rule.description_contains}"`
        : `description does not contain "${rule.description_contains}"`,
    };
  }

  // No description — fall through to amount-only matching
  const reasons: string[] = [];
  let matches = true;
  if (rule.amount_min !== null) {
    if (amount >= rule.amount_min) reasons.push(`amount ${amount} ≥ min ${rule.amount_min}`);
    else { matches = false; reasons.push(`amount ${amount} < min ${rule.amount_min}`); }
  }
  if (rule.amount_max !== null) {
    if (amount <= rule.amount_max) reasons.push(`amount ${amount} ≤ max ${rule.amount_max}`);
    else { matches = false; reasons.push(`amount ${amount} > max ${rule.amount_max}`); }
  }

  return {
    ruleId: rule.id,
    ruleName: rule.rule_name,
    matches,
    reason: reasons.join("; ") || (matches ? "no conditions — matches everything" : "no match"),
  };
}
