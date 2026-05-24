import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agent Mission Control OS",
  description: "Observability and Execution Interface for LangGraph Pipelines",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-[100dvh] bg-zinc-950 text-zinc-400 selection:bg-accent-900 selection:text-emerald-100">
        {children}
      </body>
    </html>
  );
}
