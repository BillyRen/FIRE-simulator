import { getLocale } from "next-intl/server";

const OG_LOCALE_MAP: Record<string, string> = {
  en: "en_US",
  zh: "zh_CN",
};

export async function getOgLocale(): Promise<string> {
  const locale = await getLocale();
  return OG_LOCALE_MAP[locale] ?? "en_US";
}
