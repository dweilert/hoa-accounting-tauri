import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export type Accessor<T> = (row: T) => string | number | null | undefined;

function compare(a: string | number | null | undefined, b: string | number | null | undefined): number {
  const aNil = a === null || a === undefined || a === "";
  const bNil = b === null || b === undefined || b === "";
  if (aNil && bNil) return 0;
  if (aNil) return 1;
  if (bNil) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function useTableSort<T>(
  rows: T[],
  accessors: Record<string, Accessor<T>>,
  initialKey: string | null = null,
  initialDir: SortDir = "asc",
) {
  const [sortKey, setSortKey] = useState<string | null>(initialKey);
  const [sortDir, setSortDir] = useState<SortDir>(initialDir);

  function toggleSort(key: string) {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }

  const sorted = useMemo(() => {
    const acc = sortKey ? accessors[sortKey] : undefined;
    if (!acc) return rows;
    const out = [...rows].sort((a, b) => compare(acc(a), acc(b)));
    return sortDir === "asc" ? out : out.reverse();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sortKey, sortDir]);

  return { sorted, sortKey, sortDir, toggleSort };
}
