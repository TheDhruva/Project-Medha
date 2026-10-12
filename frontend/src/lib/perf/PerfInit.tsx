"use client";

import { useEffect } from "react";
import { initWebVitals } from "@/lib/perf/vitals";

export function PerfInit() {
  useEffect(() => {
    initWebVitals();
  }, []);
  return null;
}
