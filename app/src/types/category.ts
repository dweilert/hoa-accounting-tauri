import { z } from "zod";

export const CategoryType = z.enum(["INCOME", "EXPENSE", "TRANSFER"]);
export const FundCode = z.enum(["OPERATING", "RESERVE", "SPECIAL"]);

export const CategorySchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  category_type: CategoryType,
  fund_code: FundCode,
  sort_order: z.number(),
  group_name: z.string().nullable(),
  description: z.string().nullable(),
  active_flag: z.number(),
  system_required: z.number(),
  created_at: z.string(),
});

export type Category = z.infer<typeof CategorySchema>;
export type CategoryTypeValue = z.infer<typeof CategoryType>;
export type FundCodeValue = z.infer<typeof FundCode>;

export const CategoryFormSchema = z.object({
  code: z.string().min(1).max(30).regex(/^[A-Z0-9_]+$/, "Uppercase letters, digits, and underscores only"),
  name: z.string().min(1).max(100),
  category_type: CategoryType,
  fund_code: FundCode,
  sort_order: z.coerce.number().int().min(0).max(9999),
  group_name: z.string().max(80).optional(),
  description: z.string().max(500).optional(),
  active_flag: z.coerce.number().int().min(0).max(1),
});

export type CategoryFormValues = z.infer<typeof CategoryFormSchema>;
