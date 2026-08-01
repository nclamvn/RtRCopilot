import {redirect} from "next/navigation";

/**
 * TIP-011 route consolidation: the Files workspace now lives under the shell
 * at /files. The legacy root URL redirects there, preserving the query string
 * so pre-move deep links minted against `/?version=…&page=…` (TIP-008
 * locator contract) keep opening the exact position.
 */
export default async function RootRedirect({searchParams}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      params.append(key, item);
    }
  }
  const query = params.toString();
  redirect(query ? `/files?${query}` : "/files");
}
