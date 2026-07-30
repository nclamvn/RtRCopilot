import type {Metadata} from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "RtR Copilot V2 Foundation",
  description: "Secure platform foundation status",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="vi"><body>{children}</body></html>;
}
