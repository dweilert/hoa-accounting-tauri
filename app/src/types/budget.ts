import { z } from "zod";

export const BudgetStatus = z.enum(["DRAFT", "APPROVED", "ARCHIVED"]);
export type BudgetStatusValue = z.infer<typeof BudgetStatus>;

export const BudgetSchema = z.object({
  id: z.number(),
  fiscal_year: z.number(),
  fund_code: z.string(),
  status: BudgetStatus,
  notes: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Budget = z.infer<typeof BudgetSchema>;

export const BudgetLineSchema = z.object({
  id: z.number(),
  budget_id: z.number(),
  category_id: z.number(),
  fiscal_period: z.number(),
  budget_amount: z.number(),
});
export type BudgetLine = z.infer<typeof BudgetLineSchema>;

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

export const STATUS_COLORS: Record<BudgetStatusValue, string> = {
  DRAFT: "bg-yellow-100 text-yellow-700",
  APPROVED: "bg-green-100 text-green-700",
  ARCHIVED: "bg-gray-100 text-gray-500",
};
