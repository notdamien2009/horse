import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./market.css";

export const metadata: Metadata = {
  title: { default: "FurlongIQ · Today's Racing", template: "%s · FurlongIQ" },
  description: "FurlongIQ racing market intelligence: daily UK & Irish racecards, FIQ speed ratings, market movers and trainer profiles.",
  applicationName: "FurlongIQ",
};

export const viewport: Viewport = { themeColor: "#020617" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" />
        <script
          dangerouslySetInnerHTML={{
            __html: `try{document.documentElement.dataset.theme=localStorage.getItem('speeds-theme')||'dark'}catch{document.documentElement.dataset.theme='dark'}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
