import type { Metadata } from "next";
import Navbar from "./components/Navbar";
import { AuthProvider } from "./lib/authContext";
import "./globals.css";

export const metadata: Metadata = { title: "CapitalCompass" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Navbar />
          <main>{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
