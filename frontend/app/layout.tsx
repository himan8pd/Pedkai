import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import AuthLayout from "./layout-auth";
import { ThemeProvider } from "./context/ThemeContext";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "pedk.ai | NOC Command Center",
  description: "Autonomous Network Operations & MTTR Reduction",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} antialiased`}>
        <ThemeProvider>
          <AuthLayout>{children}</AuthLayout>
        </ThemeProvider>
      </body>
    </html>
  );
}
