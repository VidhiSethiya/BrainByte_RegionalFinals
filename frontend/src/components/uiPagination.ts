import type { TablePaginationConfig } from "antd/es/table";

/** Simple Ant Design client-side pagination — pages the rows already in `dataSource`. */
export const UI_PAGE_SIZE = 10;

/** Fetch this many rows from list APIs, then paginate in the UI. */
export const FETCH_ALL_PAGE_SIZE = 200;

export const uiPagination: TablePaginationConfig = {
  pageSize: UI_PAGE_SIZE,
  showSizeChanger: true,
  pageSizeOptions: ["10", "20", "50", "100"],
  showTotal: (total, range) => `${range[0]}–${range[1]} of ${total}`,
};

/** Same shape for Ant Design List.pagination */
export const listPagination = {
  pageSize: UI_PAGE_SIZE,
  showSizeChanger: true,
  pageSizeOptions: ["10", "20", "50", "100"],
  showTotal: (total: number, range: [number, number]) => `${range[0]}–${range[1]} of ${total}`,
};
