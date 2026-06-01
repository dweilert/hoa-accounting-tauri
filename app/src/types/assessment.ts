import { z } from "zod";

export const ChargeType = z.enum(["DUES", "LATE_FEE", "LEGAL_FEE", "OTHER"]);
export const AssessmentStatus = z.enum(["OPEN", "PARTIAL", "PAID", "VOID", "WRITTEN_OFF"]);
export type ChargeTypeValue = z.infer<typeof ChargeType>;
export type AssessmentStatusValue = z.infer<typeof AssessmentStatus>;

export const AssessmentSchema = z.object({
  id: z.number(),
  lot_id: z.number(),
  owner_id: z.number().nullable(),
  charge_type: ChargeType,
  amount: z.number(),
  assessment_date: z.string(),
  due_date: z.string().nullable(),
  description: z.string().nullable(),
  status: AssessmentStatus,
  category_id: z.number().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Assessment = z.infer<typeof AssessmentSchema>;

export const AssessmentFormSchema = z.object({
  lot_id: z.coerce.number().int().positive("Required"),
  owner_id: z.coerce.number().int().optional(),
  charge_type: ChargeType,
  amount: z.coerce.number().positive("Must be > 0"),
  assessment_date: z.string().min(1, "Required"),
  due_date: z.string().optional(),
  description: z.string().optional(),
  category_id: z.coerce.number().int().optional(),
});
export type AssessmentFormValues = z.infer<typeof AssessmentFormSchema>;

export const CHARGE_TYPE_LABELS: Record<ChargeTypeValue, string> = {
  DUES: "HOA Dues",
  LATE_FEE: "Late Fee",
  LEGAL_FEE: "Legal Fee",
  OTHER: "Other Charge",
};

export const STATUS_COLORS: Record<AssessmentStatusValue, string> = {
  OPEN: "bg-yellow-100 text-yellow-700",
  PARTIAL: "bg-blue-100 text-blue-700",
  PAID: "bg-green-100 text-green-700",
  VOID: "bg-gray-100 text-gray-400",
  WRITTEN_OFF: "bg-red-100 text-red-400",
};
