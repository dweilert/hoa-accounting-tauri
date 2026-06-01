import { z } from "zod";

export const BillStatus = z.enum(["OPEN", "PARTIAL", "PAID", "VOID"]);
export type BillStatusValue = z.infer<typeof BillStatus>;

export const VendorBillSchema = z.object({
  id: z.number(),
  vendor_id: z.number(),
  vendor_name: z.string().optional(), // joined
  invoice_number: z.string(),
  invoice_date: z.string(),
  due_date: z.string().nullable(),
  amount: z.number(),
  fund_code: z.enum(["OPERATING", "RESERVE", "SPECIAL"]),
  status: BillStatus,
  category_id: z.number().nullable(),
  category_code: z.string().nullable().optional(), // joined
  description: z.string().nullable(),
  amount_paid: z.number().optional(), // computed from bill_payments
  created_at: z.string(),
  updated_at: z.string(),
});

export type VendorBill = z.infer<typeof VendorBillSchema>;

export const VendorBillFormSchema = z.object({
  vendor_id: z.coerce.number().min(1, "Select a vendor"),
  invoice_number: z.string().min(1, "Required").max(50),
  invoice_date: z.string().min(1, "Required"),
  due_date: z.string().optional(),
  amount: z.coerce.number().refine((n) => n !== 0, "Amount cannot be zero"),
  fund_code: z.enum(["OPERATING", "RESERVE", "SPECIAL"]),
  category_id: z.coerce.number().nullable(),
  description: z.string().max(500).optional(),
});

export type VendorBillFormValues = z.infer<typeof VendorBillFormSchema>;

export const BillPaymentSchema = z.object({
  id: z.number(),
  vendor_bill_id: z.number(),
  payment_date: z.string(),
  amount: z.number(),
  bank_account_id: z.number(),
  bank_account_name: z.string().optional(), // joined
  check_number: z.string().nullable(),
  notes: z.string().nullable(),
  created_at: z.string(),
});

export type BillPayment = z.infer<typeof BillPaymentSchema>;

export const BillPaymentFormSchema = z.object({
  payment_date: z.string().min(1, "Required"),
  amount: z.coerce.number().refine((n) => n !== 0, "Amount cannot be zero"),
  bank_account_id: z.coerce.number().min(1, "Select a bank account"),
  check_number: z.string().max(20).optional(),
  notes: z.string().max(500).optional(),
});

export type BillPaymentFormValues = z.infer<typeof BillPaymentFormSchema>;
