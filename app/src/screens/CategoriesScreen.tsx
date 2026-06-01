import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import {
  listCategories,
  insertCategory,
  updateCategory,
  deleteCategory,
} from "../repositories/categoryRepo";
import {
  CategoryFormSchema,
  type Category,
  type CategoryFormValues,
  type CategoryTypeValue,
} from "../types/category";

const TYPE_ORDER: CategoryTypeValue[] = ["INCOME", "EXPENSE", "TRANSFER"];
const TYPE_LABEL: Record<CategoryTypeValue, string> = {
  INCOME: "Income",
  EXPENSE: "Expense",
  TRANSFER: "Transfer",
};
const TYPE_COLOR: Record<CategoryTypeValue, string> = {
  INCOME: "bg-green-50 border-green-200",
  EXPENSE: "bg-red-50 border-red-200",
  TRANSFER: "bg-blue-50 border-blue-200",
};

// ── Form ─────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: Category;
  onSave: (values: CategoryFormValues) => Promise<void>;
  onCancel: () => void;
};

function CategoryForm({ initial, onSave, onCancel }: FormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<CategoryFormValues>({
    code: initial?.code ?? "",
    name: initial?.name ?? "",
    category_type: initial?.category_type ?? "EXPENSE",
    fund_code: initial?.fund_code ?? "OPERATING",
    sort_order: initial?.sort_order ?? 0,
    group_name: initial?.group_name ?? "",
    description: initial?.description ?? "",
    active_flag: initial?.active_flag ?? 1,
  });
  const [errors, setErrors] = useState<Partial<Record<keyof CategoryFormValues, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof CategoryFormValues>(k: K, v: CategoryFormValues[K]) =>
    setValues((prev) => ({ ...prev, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = CategoryFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) {
        const key = issue.path[0] as keyof CategoryFormValues;
        errs[key] = issue.message;
      }
      setErrors(errs);
      return;
    }
    setSaving(true);
    try {
      await onSave(result.data);
    } finally {
      setSaving(false);
    }
  }

  const field = (label: string, children: ReactNode, error?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );

  const input = (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
    />
  );

  const select = (
    props: React.SelectHTMLAttributes<HTMLSelectElement>,
    options: [string, string][]
  ) => (
    <select
      {...props}
      className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
    >
      {options.map(([val, label]) => (
        <option key={val} value={val}>
          {label}
        </option>
      ))}
    </select>
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {field(
          "Code",
          input({
            value: values.code,
            onChange: (e) => set("code", e.target.value.toUpperCase()),
            disabled: isEdit,
            placeholder: "e.g. LANDSCAPING",
          }),
          errors.code
        )}
        {field(
          "Type",
          select(
            {
              value: values.category_type,
              onChange: (e) => set("category_type", e.target.value as CategoryTypeValue),
              disabled: isEdit,
            },
            [
              ["INCOME", "Income"],
              ["EXPENSE", "Expense"],
              ["TRANSFER", "Transfer"],
            ]
          ),
          errors.category_type
        )}
      </div>

      {field(
        "Name",
        input({
          value: values.name,
          onChange: (e) => set("name", e.target.value),
          placeholder: "Display name",
        }),
        errors.name
      )}

      <div className="grid grid-cols-2 gap-4">
        {field(
          "Fund",
          select(
            {
              value: values.fund_code,
              onChange: (e) => set("fund_code", e.target.value as CategoryFormValues["fund_code"]),
            },
            [
              ["OPERATING", "Operating"],
              ["RESERVE", "Reserve"],
              ["SPECIAL", "Special"],
            ]
          ),
          errors.fund_code
        )}
        {field(
          "Sort Order",
          input({
            type: "number",
            value: values.sort_order,
            onChange: (e) => set("sort_order", Number(e.target.value)),
            min: 0,
            max: 9999,
          }),
          errors.sort_order
        )}
      </div>

      {field(
        "Group (optional)",
        input({
          value: values.group_name ?? "",
          onChange: (e) => set("group_name", e.target.value),
          placeholder: "e.g. Landscaping",
        }),
        errors.group_name
      )}

      {field(
        "Description (optional)",
        input({
          value: values.description ?? "",
          onChange: (e) => set("description", e.target.value),
        }),
        errors.description
      )}

      {isEdit && (
        <div className="flex gap-4">
          {(["1", "0"] as const).map((val) => (
            <label key={val} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="active_flag"
                value={val}
                checked={String(values.active_flag) === val}
                onChange={() => set("active_flag", Number(val))}
              />
              {val === "1" ? "Active" : "Inactive"}
            </label>
          ))}
        </div>
      )}

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Category"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "add" }
  | { mode: "edit"; category: Category }
  | null;

// Workaround: ReactNode type needs to be imported here since we use it in field()
import type { ReactNode } from "react";

export function CategoriesScreen() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const load = useCallback(async () => {
    try {
      setCategories(await listCategories());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: CategoryFormValues) {
    if (modal?.mode === "edit") {
      await updateCategory(modal.category.id, values);
    } else {
      await insertCategory(values);
    }
    setModal(null);
    await load();
  }

  async function handleDelete(cat: Category) {
    if (!confirm(`Delete "${cat.name}"? This cannot be undone.`)) return;
    try {
      await deleteCategory(cat.id);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  const grouped = TYPE_ORDER.map((type) => ({
    type,
    rows: categories.filter((c) => c.category_type === type),
  }));

  const fundBadge = (f: string) => {
    const colors: Record<string, string> = {
      OPERATING: "bg-gray-100 text-gray-600",
      RESERVE: "bg-yellow-100 text-yellow-700",
      SPECIAL: "bg-purple-100 text-purple-700",
    };
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[f] ?? ""}`}>
        {f}
      </span>
    );
  };

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Chart of Accounts</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {categories.length} categories
          </p>
        </div>
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add Category
        </button>
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && grouped.map(({ type, rows }) => (
        rows.length === 0 ? null : (
          <div key={type} className={`mb-6 border rounded-lg overflow-hidden ${TYPE_COLOR[type]}`}>
            <div className="px-4 py-2 border-b">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-600">
                {TYPE_LABEL[type]}
              </span>
            </div>
            <table className="w-full text-sm bg-white">
              <thead className="border-b bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 text-xs">Code</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 text-xs">Name</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 text-xs">Fund</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 text-xs">Group</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 text-xs">Status</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((cat) => (
                  <tr key={cat.id} className={cat.active_flag ? "" : "opacity-50"}>
                    <td className="px-4 py-2 font-mono text-xs text-gray-700">{cat.code}</td>
                    <td className="px-4 py-2 text-gray-900">
                      {cat.name}
                      {cat.description && (
                        <span className="ml-2 text-xs text-gray-400">{cat.description}</span>
                      )}
                    </td>
                    <td className="px-4 py-2">{fundBadge(cat.fund_code)}</td>
                    <td className="px-4 py-2 text-xs text-gray-500">{cat.group_name ?? "—"}</td>
                    <td className="px-4 py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${
                          cat.active_flag
                            ? "bg-green-100 text-green-700"
                            : "bg-gray-100 text-gray-500"
                        }`}
                      >
                        {cat.active_flag ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right space-x-2">
                      <button
                        onClick={() => setModal({ mode: "edit", category: cat })}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      {!cat.system_required && (
                        <button
                          onClick={() => handleDelete(cat)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ))}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Category" : `Edit — ${modal.category.code}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <CategoryForm
              initial={modal.category}
              onSave={handleSave}
              onCancel={() => setModal(null)}
            />
          ) : (
            <CategoryForm
              onSave={handleSave}
              onCancel={() => setModal(null)}
            />
          )}
        </Modal>
      )}
    </div>
  );
}
