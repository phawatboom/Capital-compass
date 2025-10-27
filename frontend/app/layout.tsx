import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/app/lib/authContext";
import SiteHeader from "@/app/components/siteHeader";
// import SiteFooter from "@/app/components/siteFooter"; // optional

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Capital Compass",
  description: "",
  generator: "",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      {/* Make the page a flex column and full viewport height */}
      <body className={`${inter.className} min-h-dvh flex flex-col`}>
        <AuthProvider>
          <SiteHeader />

          {/* Let main grow and remove bottom padding to avoid the white band */}
          <main className="flex-1 mx-auto w-full max-w-screen-2xl px-4 sm:px-6 lg:px-8 pt-6 pb-0">
            {children}
          </main>

          {/* If you have a shared footer, render it here so it always sits at the bottom */}
          {/* <SiteFooter /> */}
        </AuthProvider>
      </body>
    </html>
  );
}
