import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { routing } from "./routing";

export default getRequestConfig(async () => {
  // 1. Check cookie
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get("locale")?.value;

  // 2. Check Accept-Language header for auto-detection
  let detectedLocale: string | undefined;
  if (!cookieLocale) {
    const headerStore = await headers();
    const acceptLang = headerStore.get("accept-language") ?? "";
    if (acceptLang.toLowerCase().includes("zh")) {
      detectedLocale = "zh";
    } else if (acceptLang.toLowerCase().includes("en")) {
      detectedLocale = "en";
    }
  }

  const locale =
    routing.locales.includes(cookieLocale as "zh" | "en")
      ? cookieLocale!
      : routing.locales.includes(detectedLocale as "zh" | "en")
        ? detectedLocale!
        : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
