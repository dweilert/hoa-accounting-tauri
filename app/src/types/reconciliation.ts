import { z } from "zod";

export const ReconStatus = z.enum(["OPEN", "FINALIZED"]);
export type ReconStatusValue = z.infer<typeof ReconStatus>;

export const BankReconciliationSchema = z.object({
  id: z.number(),
  bank_account_id: z.number(),
  statement_ending_date: z.string(),
  statement_ending_balance: z.number(),
  beginning_balance: z.number(),
  book_balance: z.number().nullable(),
  status: ReconStatus,
  notes: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type BankReconciliation = z.infer<typeof BankReconciliationSchema>;

export const BankTransactionSchema = z.object({
  id: z.number(),
  bank_account_id: z.number(),
  transaction_date: z.string(),
  amount: z.number(),
  description: z.string().nullable(),
  memo: z.string().nullable(),
  transaction_type: z.string().nullable(),
  fitid: z.string().nullable(),
  dedup_key: z.string().nullable(),
  validation_status: z.enum(["UNVALIDATED", "VALIDATED", "IGNORED"]),
  import_batch_id: z.number().nullable(),
  created_at: z.string(),
});
export type BankTransaction = z.infer<typeof BankTransactionSchema>;
