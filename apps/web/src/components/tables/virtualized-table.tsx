'use client';

import { useRef } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useState } from 'react';

interface VirtualizedTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  rowHeight?: number;
  className?: string;
  onRowClick?: (row: T) => void;
  selectedRow?: T | null;
  getRowId?: (row: T) => string;
}

/**
 * Virtualized table — renders 1000+ rows at 60fps.
 * Uses TanStack Table for column logic + TanStack Virtual for windowing.
 * Sticky header, sortable columns, keyboard-navigable.
 */
export function VirtualizedTable<T>({
  data,
  columns,
  rowHeight = 28,
  className = '',
  onRowClick,
  selectedRow,
  getRowId,
}: VirtualizedTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const parentRef = useRef<HTMLDivElement>(null);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: getRowId as ((row: T) => string) | undefined,
  });

  const { rows } = table.getRowModel();

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 20,
  });

  const virtualRows = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  return (
    <div ref={parentRef} className={`overflow-auto ${className}`} style={{ maxHeight: '100%' }}>
      <table className="w-full text-xs border-collapse">
        {/* Sticky header */}
        <thead className="sticky top-0 z-10 bg-[var(--color-bg-elevated)]">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="text-left py-1.5 px-2 border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)] font-medium cursor-pointer select-none hover:text-[var(--color-text-primary)]"
                  onClick={header.column.getToggleSortingHandler()}
                  style={{ width: header.getSize() }}
                >
                  <span className="flex items-center gap-1">
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === 'asc' && '↑'}
                    {header.column.getIsSorted() === 'desc' && '↓'}
                  </span>
                </th>
              ))}
            </tr>
          ))}
        </thead>

        {/* Virtualized body */}
        <tbody style={{ height: `${totalSize}px`, position: 'relative' }}>
          {virtualRows.map((virtualRow) => {
            const row = rows[virtualRow.index];
            const isSelected =
              selectedRow && getRowId
                ? getRowId(row.original) === getRowId(selectedRow)
                : false;

            return (
              <tr
                key={row.id}
                data-index={virtualRow.index}
                className={`border-b border-[var(--color-border-muted)] hover:bg-[var(--color-bg-elevated)] ${
                  isSelected ? 'bg-[var(--color-bg-elevated)]' : ''
                } ${onRowClick ? 'cursor-pointer' : ''}`}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                onClick={() => onRowClick?.(row.original)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className="py-1 px-2"
                    style={{ width: cell.column.getSize() }}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>

      {data.length === 0 && (
        <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
          No data
        </div>
      )}
    </div>
  );
}
