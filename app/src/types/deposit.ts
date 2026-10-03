import { z } from "zod";

export const DepositStatus = z.enum(["OPEN", "POSTED"]);
export type DepositStatusValue = z.infer<typeof DepositStatus>;

export const DepositBatchSchema = z.object({
  id: z.number(),
  deposit_date: z.string(),
  bank_account_id: z.number(),
  total_amount: z.number(),
  check_count: z.number(),
  notes: z.string().nullable(),
  status: DepositStatus,
  bank_transaction_id: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type DepositBatch = z.infer<typeof DepositBatchSchema>;

export const PaymentMethodType = z.enum(["CHECK", "ACH", "ONLINE", "CASH", "OTHER"]);
export type PaymentMethodValue = z.infer<typeof PaymentMethodType>;

export const PaymentType = z.enum([
  "DUES",
  "SPECIAL_ASSESSMENT",
  "RESALE_FEE",
  "NSF_FEE",
  "REIMBURSEMENT",
  "OTHER",
]);
export type PaymentTypeValue = z.infer<typeof PaymentType>;

export const PAYMENT_TYPE_LABELS: Record<PaymentTypeValue, string> = {
  DUES:               "Monthly Dues",
  SPECIAL_ASSESSMENT: "Special Assessment",
  RESALE_FEE:         "Resale / Transfer Fee",
  NSF_FEE:            "NSF / Returned Check Fee",
  REIMBURSEMENT:      "Expense Reimbursement",
  OTHER:              "Other",
};

export const PaymentSchema = z.object({
  id: z.number(),
  lot_id: z.number(),
  owner_id: z.number().nullable(),
  deposit_batch_id: z.number().nullable(),
  payment_date: z.string(),
  amount: z.number(),
  payment_method: PaymentMethodType,
  payment_type: PaymentType.default("DUES"),
  check_number: z.string().nullable(),
  memo: z.string().nullable(),
  created_at: z.string(),
});
export type Payment = z.infer<typeof PaymentSchema>;

export const PaymentFormSchema = z.object({
  lot_id: z.coerce.number().int().positive("Required"),
  owner_id: z.coerce.number().int().optional(),
  payment_date: z.string().min(1, "Required"),
  amount: z.coerce.number().positive("Must be > 0"),
  payment_method: PaymentMethodType,
  payment_type: PaymentType.default("DUES"),
  check_number: z.string().optional(),
  memo: z.string().optional(),
});
export type PaymentFormValues = z.infer<typeof PaymentFormSchema>;
