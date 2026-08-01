import {redirect} from "next/navigation";

/**
 * TIP-011 route contract: the Files area lives at /files. The workspace
 * itself still renders at "/" until Builder C migrates it under the shell,
 * so this route redirects to keep the shell nav's `/files` link stable.
 * The query string is preserved so TIP-008 deep links minted against
 * `/files?version=…&page=…` (the shared Evidence Rail's locator contract)
 * keep opening the exact position.
 */
export default async function FilesRoute({searchParams}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      params.append(key, item);
    }
  }
  const query = params.toString();
  redirect(query ? `/?${query}` : "/");
}
