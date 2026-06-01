import { z } from "zod";

export const LotSchema = z.object({
  id: z.number(),
  lot_number: z.string(),
  street_address_1: z.string().nullable(),
  street_address_2: z.string().nullable(),
  city: z.string().nullable(),
  state: z.string().nullable(),
  postal_code: z.string().nullable(),
  legal_description: z.string().nullable(),
  active_flag: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Lot = z.infer<typeof LotSchema>;

export const LotWithOwnerSchema = LotSchema.extend({
  owner_names: z.string().nullable(),
});

export type LotWithOwner = z.infer<typeof LotWithOwnerSchema>;

export const LotFormSchema = z.object({
  lot_number: z.string().min(1).max(20),
  street_address_1: z.string().max(100).optional(),
  street_address_2: z.string().max(100).optional(),
  city: z.string().max(60).optional(),
  state: z.string().max(2).optional(),
  postal_code: z.string().max(10).optional(),
  legal_description: z.string().max(500).optional(),
  active_flag: z.coerce.number().int().min(0).max(1),
});

export type LotFormValues = z.infer<typeof LotFormSchema>;
