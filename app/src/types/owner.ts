import { z } from "zod";

export const OwnerType = z.enum(["PERSON", "ENTITY", "TRUST"]);
export type OwnerTypeValue = z.infer<typeof OwnerType>;

export const OwnerSchema = z.object({
  id: z.number(),
  owner_type: OwnerType,
  display_name: z.string(),
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  entity_name: z.string().nullable(),
  mailing_address_1: z.string().nullable(),
  mailing_address_2: z.string().nullable(),
  city: z.string().nullable(),
  state: z.string().nullable(),
  postal_code: z.string().nullable(),
  phone: z.string().nullable(),
  home_phone: z.string().nullable(),
  email: z.string().nullable(),
  notes: z.string().nullable(),
  active_flag: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Owner = z.infer<typeof OwnerSchema>;

export const OwnerWithLotsSchema = OwnerSchema.extend({
  lot_numbers: z.string().nullable(),
});

export type OwnerWithLots = z.infer<typeof OwnerWithLotsSchema>;

export const OwnerFormSchema = z.object({
  owner_type: OwnerType,
  display_name: z.string().min(1).max(100),
  first_name: z.string().max(60).optional(),
  last_name: z.string().max(60).optional(),
  entity_name: z.string().max(100).optional(),
  mailing_address_1: z.string().max(100).optional(),
  mailing_address_2: z.string().max(100).optional(),
  city: z.string().max(60).optional(),
  state: z.string().max(2).optional(),
  postal_code: z.string().max(10).optional(),
  phone: z.string().max(20).optional(),
  home_phone: z.string().max(20).optional(),
  email: z.string().email().max(100).optional().or(z.literal("")),
  notes: z.string().max(1000).optional(),
  active_flag: z.coerce.number().int().min(0).max(1),
});

export type OwnerFormValues = z.infer<typeof OwnerFormSchema>;
