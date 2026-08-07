import "@ant-design/v5-patch-for-react-19";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
  },
});

/**
 * The single source of colour, radius and type for the whole app.
 *
 * Hexes are permitted here and in `components/chartTheme.ts` only — a component
 * that types a `#` has bypassed the design system.
 */
const ticketSphereTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#A84A4D",
    colorInfo: "#4A7C82",
    colorSuccess: "#4F7A5B",
    colorWarning: "#B08D57",
    colorError: "#A84A4D",

    colorBgLayout: "#FCFBF8",
    colorBgContainer: "#FFFFFF",
    colorBgElevated: "#FFFFFF",

    colorText: "#1A1A1A",
    colorTextSecondary: "#5E5E5E",
    colorTextTertiary: "#8A8A8A",
    colorBorder: "#EBE9E1",
    colorBorderSecondary: "#EBE9E1",

    borderRadius: 4,
    borderRadiusLG: 8,
    borderRadiusSM: 4,

    fontFamily:
      "'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
    fontSize: 14,
    fontSizeHeading1: 32,
    fontSizeHeading2: 24,
    fontSizeHeading3: 20,
    lineHeight: 1.43,

    controlHeight: 32,
    boxShadow: "0 4px 12px rgba(0,0,0,0.03)",
    boxShadowSecondary: "0 8px 24px rgba(0,0,0,0.06)",
    wireframe: false,
  },
  components: {
    Layout: { bodyBg: "#FCFBF8", headerBg: "#FFFFFF", siderBg: "#F5F4F0", headerHeight: 56 },
    Menu: {
      itemBg: "#F5F4F0",
      itemSelectedBg: "#FFFFFF",
      itemSelectedColor: "#A84A4D",
      itemHoverBg: "#FCFBF8",
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: "#F5F4F0",
      headerColor: "#5E5E5E",
      rowHoverBg: "#FCFBF8",
      borderColor: "#EBE9E1",
      cellPaddingBlock: 12,
    },
    Card: { paddingLG: 24, headerBg: "transparent" },
    Button: { primaryShadow: "none", defaultShadow: "none", contentFontSize: 14 },
    Input: {
      activeBorderColor: "#4A7C82",
      hoverBorderColor: "#4A7C82",
      activeShadow: "0 0 0 2px rgba(74,124,130,0.10)",
    },
    Tag: { defaultBg: "#F5F4F0", defaultColor: "#5E5E5E" },
  },
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider theme={ticketSphereTheme}>
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </StrictMode>
);
