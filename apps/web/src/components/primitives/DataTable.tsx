/**
 * Accessible tables.
 *
 * These are the real alternative to the canvas, so they are not a degraded
 * afterthought: sortable headers are buttons with `aria-sort`, long IDs wrap,
 * the selected row is marked with `aria-current`, and rows use `content-
 * visibility` so a 5000-row task queue still opens instantly.
 */
import type { ReactNode } from "react"

export type SortDir = "asc" | "desc"

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  /** Value used for sorting. Omit to make the column unsortable. */
  sortValue?: (row: T) => number | string
  align?: "left" | "right"
  width?: string
  mono?: boolean
}

export interface DataTableProps<T> {
  caption: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  sort: { key: string; dir: SortDir } | null
  onSort: (key: string) => void
  onRowClick?: (row: T) => void
  selectedKey?: string | null
  emptyBody?: ReactNode
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  onSort,
  onRowClick,
  selectedKey,
  emptyBody,
}: DataTableProps<T>) {
  if (rows.length === 0 && emptyBody !== undefined) return <>{emptyBody}</>
  return (
    <table className="w-full border-collapse text-[12px]">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-rule">
          {columns.map((column) => {
            const isSorted = sort?.key === column.key
            const ariaSort = isSorted ? (sort?.dir === "asc" ? "ascending" : "descending") : column.sortValue ? "none" : undefined
            return (
              <th
                key={column.key}
                scope="col"
                aria-sort={ariaSort}
                style={column.width !== undefined ? { width: column.width } : undefined}
                className={`stencil px-2 py-1.5 text-[9px] font-semibold text-ink-3 ${
                  column.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {column.sortValue !== undefined ? (
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    className="inline-flex items-center gap-1 hover:text-ink"
                  >
                    {column.header}
                    <span aria-hidden="true" className="text-[8px]">
                      {isSorted ? (sort?.dir === "asc" ? "▲" : "▼") : "⇅"}
                    </span>
                  </button>
                ) : (
                  column.header
                )}
              </th>
            )
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row)
          const selected = selectedKey !== undefined && selectedKey !== null && selectedKey === key
          return (
            <tr
              key={key}
              className={`long-list border-b border-rule/50 ${
                selected ? "bg-teal-wash" : "hover:bg-raised"
              } ${onRowClick !== undefined ? "cursor-pointer" : ""}`}
              aria-current={selected ? "true" : undefined}
              onClick={onRowClick !== undefined ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick !== undefined
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
              }
              tabIndex={onRowClick !== undefined ? 0 : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-2 py-1.5 align-top text-ink ${
                    column.align === "right" ? "text-right" : "text-left"
                  } ${column.mono === true ? "num" : ""}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Stable sort helper that never mutates the input. */
export function sortRows<T>(rows: readonly T[], key: string, dir: SortDir, columns: Column<T>[]): T[] {
  const column = columns.find((c) => c.key === key)
  if (column?.sortValue === undefined) return [...rows]
  const factor = dir === "asc" ? 1 : -1
  return rows.toSorted((a, b) => {
    const va = column.sortValue?.(a)
    const vb = column.sortValue?.(b)
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * factor
    return String(va).localeCompare(String(vb)) * factor
  })
}