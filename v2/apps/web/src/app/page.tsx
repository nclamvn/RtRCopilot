import {redirect} from "next/navigation";

/**
 * TIP-024.5: Ask is the product's primary entry. Legacy root-level file
 * locators still carry a query string, so those links continue to open Files
 * with the exact query preserved.
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
  redirect(query ? `/files?${query}` : "/ask");
}
