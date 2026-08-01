import {redirect} from "next/navigation";

/**
 * TIP-011 route contract: the Files area lives at /files. The workspace
 * itself still renders at "/" until Builder C migrates it under the shell,
 * so this route redirects to keep the shell nav's `/files` link stable.
 */
export default function FilesRoute() {
  redirect("/");
}
