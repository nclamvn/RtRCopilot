import type {Metadata} from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Workspace",
  description: "A local place for conversations, source files and working drafts.",
  robots: {index: false, follow: false},
};

export default function WorkspaceLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
