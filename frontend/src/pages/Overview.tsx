import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { LayoutDashboard, TrendingUp, TrendingDown, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface IndexQuote {
  code: string;
  name_zh: string;
  name_en: string;
  market: "a_share" | "us";
  price: number;
  change: number;
  change_pct: number;
}

interface MarketIndicesResponse {
  indices: IndexQuote[];
  updated_at: string;
}

// Chinese market convention: red = up, green = down
function MarketChangeColor({ value }: { value: number }) {
  const isUp = value > 0;
  const isDown = value < 0;
  return (
    <span
      className={cn(
        "font-mono tabular-nums font-semibold",
        isUp && "text-red-600 dark:text-red-400",
        isDown && "text-green-600 dark:text-green-400",
        !isUp && !isDown && "text-muted-foreground"
      )}
    >
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}
    </span>
  );
}

function MarketChangePctColor({ value }: { value: number }) {
  const isUp = value > 0;
  const isDown = value < 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs font-mono tabular-nums font-semibold",
        isUp && "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
        isDown && "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
        !isUp && !isDown && "bg-muted text-muted-foreground"
      )}
    >
      {isUp && <TrendingUp className="h-3 w-3" />}
      {isDown && <TrendingDown className="h-3 w-3" />}
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function IndexCard({ index }: { index: IndexQuote }) {
  const isUp = index.change_pct > 0;
  const isDown = index.change_pct < 0;

  return (
    <div
      className={cn(
        "border rounded-xl p-4 transition-all hover:shadow-md",
        "bg-card"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold text-base truncate">{index.name_zh}</h3>
          <p className="text-xs text-muted-foreground truncate">{index.name_en}</p>
        </div>
        <span
          className={cn(
            "shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded uppercase tracking-wide",
            index.market === "a_share"
              ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
              : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
          )}
        >
          {index.market === "a_share" ? "A" : "US"}
        </span>
      </div>

      <div className="mt-3 flex items-end justify-between gap-2">
        <div>
          <div className="text-2xl font-bold font-mono tabular-nums">
            {index.price.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <MarketChangeColor value={index.change} />
            <MarketChangePctColor value={index.change_pct} />
          </div>
        </div>

        {/* Mini sparkline placeholder — shows directional arrow */}
        <div
          className={cn(
            "flex items-center justify-center w-10 h-10 rounded-full shrink-0",
            isUp && "bg-red-50 dark:bg-red-900/20",
            isDown && "bg-green-50 dark:bg-green-900/20",
            !isUp && !isDown && "bg-muted/50"
          )}
        >
          {isUp && <TrendingUp className="h-5 w-5 text-red-500 dark:text-red-400" />}
          {isDown && <TrendingDown className="h-5 w-5 text-green-500 dark:text-green-400" />}
          {!isUp && !isDown && <Minus className="h-5 w-5 text-muted-foreground" />}
        </div>
      </div>
    </div>
  );
}

function Minus(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

const REFRESH_INTERVAL_MS = 30_000; // 30 seconds

export function Overview() {
  const { t } = useTranslation();
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [updatedAt, setUpdatedAt] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchIndices = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const res = await fetch("/market-indices");
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data: MarketIndicesResponse = await res.json();
      setIndices(data.indices || []);
      setUpdatedAt(data.updated_at || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch market data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial fetch + auto-refresh
  useEffect(() => {
    fetchIndices();
    const timer = setInterval(() => fetchIndices(true), REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchIndices]);

  const aShareIndices = indices.filter((i) => i.market === "a_share");
  const usIndices = indices.filter((i) => i.market === "us");

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold">{t("overview.title")}</h1>
        </div>
        <div className="flex items-center gap-3">
          {updatedAt && (
            <span className="text-xs text-muted-foreground">
              {new Date(updatedAt).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => fetchIndices(false)}
            disabled={refreshing}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm transition-colors",
              "hover:bg-muted hover:text-foreground",
              "disabled:opacity-50"
            )}
            title={t("overview.refresh")}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            {t("overview.refresh")}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="text-sm text-destructive border border-destructive/30 rounded-lg p-3 bg-destructive/5 mb-4">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && indices.length === 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="border rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-muted rounded w-20 mb-2" />
              <div className="h-3 bg-muted rounded w-16 mb-4" />
              <div className="h-7 bg-muted rounded w-24 mb-2" />
              <div className="h-4 bg-muted rounded w-16" />
            </div>
          ))}
        </div>
      )}

      {/* A-Share indices */}
      {aShareIndices.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            A股主要指数
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
            {aShareIndices.map((idx) => (
              <IndexCard key={idx.code} index={idx} />
            ))}
          </div>
        </section>
      )}

      {/* US indices */}
      {usIndices.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            US Major Indices
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {usIndices.map((idx) => (
              <IndexCard key={idx.code} index={idx} />
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {!loading && !error && indices.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
          <LayoutDashboard className="h-12 w-12 mb-4 opacity-30" />
          <p className="text-lg font-medium">{t("overview.noData")}</p>
          <p className="text-sm mt-1">{t("overview.noDataDesc")}</p>
        </div>
      )}
    </div>
  );
}