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
    colorPrimary: "#027289",
    colorInfo: "#0E8FA8",
    colorSuccess: "#0E8A6E",
    colorWarning: "#DE8433",
    colorError: "#D6455D",

    colorBgLayout: "#F6F9FA",
    colorBgContainer: "#FFFFFF",
    colorBgElevated: "#FFFFFF",

    colorText: "#12233F",
    colorTextSecondary: "#5A6B7B",
    colorTextTertiary: "#8B9AA8",
    colorBorder: "#E1EBEF",
    colorBorderSecondary: "#EDF3F5",

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
    boxShadow: "0 4px 12px rgba(18,35,63,0.04)",
    boxShadowSecondary: "0 10px 28px rgba(18,35,63,0.10)",
    wireframe: false,
  },
  components: {
    Layout: { bodyBg: "#F6F9FA", headerBg: "#FFFFFF", siderBg: "#FBFDFD", headerHeight: 56 },
    Menu: {
      itemBg: "#FBFDFD",
      itemSelectedBg: "#E6F2F5",
      itemSelectedColor: "#027289",
      itemHoverBg: "#EDF4F6",
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: "#F3F8F9",
      headerColor: "#5A6B7B",
      rowHoverBg: "#F6FBFC",
      borderColor: "#E1EBEF",
      cellPaddingBlock: 12,
    },
    Card: { paddingLG: 24, headerBg: "transparent" },
    Button: { primaryShadow: "none", defaultShadow: "none", contentFontSize: 14 },
    Input: {
      activeBorderColor: "#027289",
      hoverBorderColor: "#4FA9BC",
      activeShadow: "0 0 0 2px rgba(2,114,137,0.12)",
    },
    Tag: { defaultBg: "#F0F5F7", defaultColor: "#5A6B7B" },
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
