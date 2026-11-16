import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "FurlongIQ · Today's Racing", template: "%s · FurlongIQ" },
  description: "Today's UK & Irish race cards with form, our speed figures and ratings.",
  applicationName: "FurlongIQ",
};

export const viewport: Viewport = { themeColor: "#070a10" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" suppressHydrationWarning>
      <head>
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
