import type {Metadata} from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Files · RtR Copilot",
  description: "Không gian xem tệp nội bộ an toàn của RtR",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="vi"><body>{children}</body></html>;
}
