import { z } from "zod";

export const VendorSchema = z.object({
  id: z.number(),
  vendor_name: z.string(),
  contact_name: z.string().nullable(),
  email: z.string().nullable(),
  phone: z.string().nullable(),
  address_1: z.string().nullable(),
  address_2: z.string().nullable(),
  city: z.string().nullable(),
  state: z.string().nullable(),
  postal_code: z.string().nullable(),
  notes: z.string().nullable(),
  active_flag: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Vendor = z.infer<typeof VendorSchema>;

export const VendorFormSchema = z.object({
  vendor_name: z.string().min(1, "Required").max(100),
  contact_name: z.string().max(100).optional(),
  email: z.string().email("Invalid email").max(100).optional().or(z.literal("")),
  phone: z.string().max(20).optional(),
  address_1: z.string().max(100).optional(),
  address_2: z.string().max(100).optional(),
  city: z.string().max(60).optional(),
  state: z.string().max(2).optional(),
  postal_code: z.string().max(10).optional(),
  notes: z.string().max(1000).optional(),
  active_flag: z.coerce.number().int().min(0).max(1),
});

export type VendorFormValues = z.infer<typeof VendorFormSchema>;
