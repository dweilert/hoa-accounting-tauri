import type { SortDir } from "../lib/useTableSort";

type Props = {
  label: string;
  col: string;
  sortKey: string | null;
  sortDir: SortDir;
  onSort: (col: string) => void;
  right?: boolean;
  className?: string;
};

export function SortableTh({ label, col, sortKey, sortDir, onSort, right, className }: Props) {
  const active = sortKey === col;
  return (
    <th
      onClick={() => onSort(col)}
      className={`px-3 py-2 text-xs font-medium text-gray-600 cursor-pointer select-none whitespace-nowrap hover:bg-gray-100 ${right ? "text-right" : "text-left"} ${className ?? ""}`}
    >
      {label} <span className="text-gray-400">{active ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}</span>
    </th>
  );
}
