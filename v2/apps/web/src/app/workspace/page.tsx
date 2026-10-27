import type {Metadata} from "next";
import {notFound} from "next/navigation";
import {WorkspaceApp} from "../../workspace/WorkspaceApp";

export const metadata: Metadata = {title: "Agent Workspace", description: "A private space for conversations, source files, and working drafts."};
export default function WorkspacePage() {
  if (process.env.WORKSPACE_UI_ENABLED !== "1") notFound();
  return <WorkspaceApp/>;
}
