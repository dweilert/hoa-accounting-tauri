import { z } from "zod";

export const EntityType = z.enum(["BANK_ACCOUNT", "LOT_DUES", "LOT_ASSESSMENT"]);
export type EntityTypeValue = z.infer<typeof EntityType>;

export const OpeningBalanceSchema = z.object({
  id: z.number(),
  entity_type: EntityType,
  entity_id: z.number(),
  as_of_date: z.string(),
  amount: z.number(),
  notes: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type OpeningBalance = z.infer<typeof OpeningBalanceSchema>;

export const OpeningBalanceFormSchema = z.object({
  as_of_date: z.string().min(1, "Required"),
  amount: z.coerce.number(),
  notes: z.string().optional(),
});
export type OpeningBalanceFormValues = z.infer<typeof OpeningBalanceFormSchema>;
