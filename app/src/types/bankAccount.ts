import { z } from "zod";

export const AccountType = z.enum(["CHECKING", "SAVINGS", "MONEY_MARKET", "OTHER"]);
export const FundCode = z.enum(["OPERATING", "RESERVE", "SPECIAL"]);

export type AccountTypeValue = z.infer<typeof AccountType>;
export type FundCodeValue = z.infer<typeof FundCode>;

export const BankAccountSchema = z.object({
  id: z.number(),
  account_name: z.string(),
  institution_name: z.string(),
  account_last4: z.string().nullable(),
  account_type: AccountType,
  fund_code: FundCode,
  active_flag: z.number(),
  opening_balance: z.number(),
  opening_balance_date: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type BankAccount = z.infer<typeof BankAccountSchema>;

export const BankAccountFormSchema = z.object({
  account_name: z.string().min(1, "Required").max(100),
  institution_name: z.string().min(1, "Required").max(100),
  account_last4: z
    .string()
    .max(4)
    .regex(/^\d*$/, "Digits only")
    .optional(),
  account_type: AccountType,
  fund_code: FundCode,
  active_flag: z.coerce.number().int().min(0).max(1),
  opening_balance: z.coerce.number(),
  opening_balance_date: z.string().optional(),
});

export type BankAccountFormValues = z.infer<typeof BankAccountFormSchema>;
